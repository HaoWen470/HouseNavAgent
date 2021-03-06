from headers import *

import sys, os, platform

import numpy as np
import random

import House3D
from House3D.roomnav import n_discrete_actions
from House3D import Environment as HouseEnv
from House3D import MultiHouseEnv
from House3D import House
from House3D.house import ALLOWED_TARGET_ROOM_TYPES, ALLOWED_PREDICTION_ROOM_TYPES, ALLOWED_OBJECT_TARGET_TYPES
from House3D.roomnav import RoomNavTask
from House3D.objnav import ObjNavTask
from House3D import objrender, load_config

import torch
import torch.nn as nn
import torch.nn.functional as F

from policy.simple_cnn_gumbel import CNNGumbelPolicy as CNNPolicy
from policy.rnn_gumbel_policy import RNNGumbelPolicy as RNNPolicy
from policy.vanila_random_policy import VanilaRandomPolicy as RandomPolicy
from policy.ddpg_cnn_critic import DDPGCNNCritic as DDPGCritic
from policy.rnn_critic import RNNCritic
from policy.joint_cnn_actor_critic import JointCNNPolicyCritic as JointModel
from policy.attentive_cnn_actor_critic import AttentiveJointCNNPolicyCritic as AttJointModel
from policy.discrete_cnn_actor_critic import DiscreteCNNPolicyCritic as A2CModel
from policy.qac_cnn_actor_critic import DiscreteCNNPolicyQFunc as QACModel
from policy.cnn_classifier import CNNClassifier
from trainer.pg import PolicyGradientTrainer as PGTrainer
from trainer.nop import NOPTrainer
from trainer.ddpg import DDPGTrainer
from trainer.ddpg_eagle_view import EagleDDPGTrainer
from trainer.rdpg import RDPGTrainer
from trainer.ddpg_joint import JointDDPGTrainer as JointTrainer
from trainer.ddpg_joint_alter import JointAlterDDPGTrainer as AlterTrainer
from trainer.a2c import A2CTrainer
from trainer.qac import QACTrainer
from trainer.dqn import DQNTrainer
from trainer.semantic import SemanticTrainer

from config import get_config, get_house_ids, get_house_targets

house_ID_dict = get_house_ids()
house_Targets_dict = get_house_targets()
all_houseIDs = house_ID_dict['small']
all_houseTargets = house_Targets_dict['small']

# only works for python 3.5
flag_parallel_init = False # (sys.version_info[1] == 5)#("Ubuntu" in platform.platform())


def set_house_IDs(partition='small', ensure_kitchen=False):
    global all_houseIDs, house_ID_dict, house_Targets_dict, all_houseTargets
    assert partition in house_ID_dict, 'Partition <{}> not found!'.format(partition)
    all_houseIDs = house_ID_dict[partition]
    all_houseTargets = house_Targets_dict[partition]
    if ensure_kitchen and (partition in ['small', 'color']):  # TODO: Currently a hack to remove house#10 in small set when not multi-target!!
        all_houseIDs = all_houseIDs[:10] + all_houseIDs[11:]
        all_houseTargets = all_houseTargets[:10] + all_houseTargets[11:]

def filter_house_IDs_by_target(fixed_target):
    global all_houseIDs, all_houseTargets
    valid_ids = [i for i, T in enumerate(all_houseTargets) if fixed_target in T]
    assert len(valid_ids) > 0, 'Invalid <fixed-target = [{}] >! No available houses!'.format(fixed_target)
    _new_all_houseIDs = [all_houseIDs[i] for i in valid_ids]
    _new_all_houseTargets = [all_houseTargets[i] for i in valid_ids]
    all_houseIDs = _new_all_houseIDs
    all_houseTargets = _new_all_houseTargets


CFG = load_config('config.json')
prefix = CFG['prefix']
csvFile = CFG['modelCategoryFile']
colorFile = CFG['colorFile']
roomTargetFile = CFG['roomTargetFile']
objectTargetFile = CFG['objectTargetFile'] if 'objectTargetFile' in CFG else None
modelObjectMapFile = CFG['modelObjectMap'] if 'modelObjectMap' in CFG else None

frame_history_len = 4
#resolution = (200, 150)
resolution = (120, 90)
resolution_dict = dict(normal=(120,90),low=(60,45),tiny=(40,30),square=(100,100),square_low=(60,60),high=(160,120))
attention_resolution = (6, 4)
attention_resolution_dict = dict(normal=(8,6),low=(6,3),high=(12,9),tiny=(4,3),row=(12,3),row_low=(8,3),row_tiny=(6,2))
observation_shape = (3 * frame_history_len, resolution[0], resolution[1])
single_observation_shape = (3, resolution[0], resolution[1])
action_shape = (4, 2)
colide_res = 1000
default_eagle_resolution = 100
n_target_instructions = len(ALLOWED_TARGET_ROOM_TYPES)
all_target_instructions = ALLOWED_TARGET_ROOM_TYPES
target_instruction_dict = dict()
for i, tp in enumerate(ALLOWED_TARGET_ROOM_TYPES):
    target_instruction_dict[tp] = i

def ensure_object_targets(flag_include_object_targets=True):
    global n_target_instructions, all_target_instructions, target_instruction_dict
    global CFG, objectTargetFile, modelObjectMapFile
    if flag_include_object_targets:
        assert 'modelObjectMap' in CFG, 'modelOjbectMap file <map_modelid_to_targetcat.json> is missing!!!'
        assert 'objectTargetFile' in CFG, 'objectTargetFile file <object_target_map.csv> is missing!!!'
        objectTargetFile = CFG['objectTargetFile']
        modelObjectMapFile = CFG['modelObjectMap']
        all_target_instructions = ALLOWED_TARGET_ROOM_TYPES + ALLOWED_OBJECT_TARGET_TYPES
        n_target_instructions = len(all_target_instructions)
        for i, tp in enumerate(all_target_instructions):
            target_instruction_dict[tp] = i
    else:
        # only room objects
        if objectTargetFile is not None:
            del CFG['objectTargetFile']
            objectTargetFile = None
        if modelObjectMapFile is not None:
            del CFG['modelObjectMap']
            modelObjectMapFile = None
        n_target_instructions = len(ALLOWED_TARGET_ROOM_TYPES)
        all_target_instructions = ALLOWED_TARGET_ROOM_TYPES
        target_instruction_dict = dict()
        for i, tp in enumerate(ALLOWED_TARGET_ROOM_TYPES):
            target_instruction_dict[tp] = i

all_aux_predictions = ALLOWED_PREDICTION_ROOM_TYPES
n_aux_predictions = len(all_aux_predictions)
all_aux_prediction_list = [None] * n_aux_predictions
for k in all_aux_predictions:
    all_aux_prediction_list[all_aux_predictions[k]] = k

debugger = None

def genCacheFile(houseID):
    return prefix + houseID + '/cachedmap1k.pkl'

##########################
# Reward Shaping Related
##########################
def set_reward_shaping_params(args):
    import House3D.roomnav as RN
    assert args['reward_type'] == 'new', 'Only support reward shaping in <new> reward!'
    if args['rew_shape_stay'] is not None:
        RN.new_stay_room_reward=args['rew_shape_stay']
    if args['rew_shape_leave'] is not None:
        RN.new_leave_penalty=args['rew_shape_leave']
    if args['rew_shape_collision'] is not None:
        RN.collision_penalty_reward=args['rew_shape_collision']
    if args['rew_shape_wrong_stop'] is not None:
        r = args['rew_shape_wrong_stop']
        if r > 0: r = -r
        RN.wrong_stop_penalty = r
    if args['rew_shape_time'] is not None:
        RN.new_time_penalty_reward=args['rew_shape_time']

##########################


def create_args(model='random', gamma = 0.9, lrate = 0.001, critic_lrate = 0.001,
                episode_len = 50, batch_size = 256,
                replay_buffer_size = int(1e6),
                grad_clip = 2, optimizer = 'adam',
                update_freq = 100, ent_penalty=None,
                decay = 0, critic_decay = 0,
                target_net_update_rate = None,
                use_batch_norm = False,
                entropy_penalty = None,
                critic_penalty=None,
                att_resolution=None,
                att_skip=0,
                batch_len=None, rnn_layers=None, rnn_cell=None, rnn_units=None,
                segment_input='none',
                depth_input=False,
                resolution_level='normal'):
    return dict(model_name=model, gamma=gamma, lrate=lrate, critic_lrate=critic_lrate,
                weight_decay=decay, critic_weight_decay=critic_decay,
                episode_len=episode_len,
                batch_size=batch_size, replay_buffer_size=replay_buffer_size,
                frame_history_len=frame_history_len,
                grad_clip=grad_clip,
                optimizer=optimizer,
                update_freq=update_freq,
                ent_penalty=entropy_penalty,
                critic_penalty=critic_penalty,
                target_net_update_rate=target_net_update_rate,
                use_batch_norm=use_batch_norm,
                # Att-CNN Params
                att_resolution=att_resolution,
                att_skip=att_skip,
                # RNN Params
                batch_len=batch_len, rnn_layers=rnn_layers, rnn_cell=rnn_cell, rnn_units=rnn_units,
                # input type
                segment_input=segment_input,
                depth_input=depth_input,
                resolution_level=resolution_level)


def process_observation_shape(model, resolution_level, segmentation_input, depth_input, history_frame_len=4, target_mask_input=False):
    global frame_history_len, resolution, attention_resolution, observation_shape, single_observation_shape
    if 'rnn' in model: history_frame_len = 1
    if history_frame_len != 4:
        frame_history_len = history_frame_len
        print('>>> Currently Stacked Frames Size = {}'.format(frame_history_len))
    if resolution_level != 'normal':
        resolution = resolution_dict[resolution_level]
        print('>>>> Resolution Changed to {}'.format(resolution))
        single_observation_shape = (3, resolution[0], resolution[1])
    if (segmentation_input is not None) and (segmentation_input != 'none'):
        if segmentation_input == 'index':
            n_chn = n_segmentation_mask
        elif segmentation_input == 'color':
            n_chn = 3
        else:
            n_chn = 6
            assert (segmentation_input == 'joint')
        single_observation_shape = (n_chn, resolution[0], resolution[1])
    else:
        # RGB input
        single_observation_shape = (3, resolution[0], resolution[1])
    if depth_input or target_mask_input:
        single_observation_shape = (single_observation_shape[0] + int(depth_input) + int(target_mask_input),
                                    single_observation_shape[1],
                                    single_observation_shape[2])
    observation_shape = (single_observation_shape[0] * frame_history_len, resolution[0], resolution[1])
    print('>> Current Observation Shape = {}'.format(observation_shape))


def create_default_args(algo='pg', model='cnn', gamma=None,
                        lrate=None, critic_lrate=None,
                        episode_len=None,
                        batch_size=None, update_freq=None,
                        use_batch_norm=True,
                        entropy_penalty=None, critic_penalty=None,
                        decay=None, critic_decay=None,
                        replay_buffer_size=None,
                        # Att-CNN Parameters
                        att_resolution_level='normal',
                        att_skip_depth=False,
                        # RNN Parameters
                        batch_len=None, rnn_layers=None, rnn_cell=None, rnn_units=None,
                        # Input Type
                        segmentation_input='none',
                        depth_input=False,
                        resolution_level='normal',
                        history_frame_len=4,
                        target_mask_input=False):
    process_observation_shape(model,
                              resolution_level=resolution_level,
                              segmentation_input=segmentation_input,
                              depth_input=depth_input,
                              history_frame_len=history_frame_len,
                              target_mask_input=target_mask_input)
    if algo == 'pg':  # policy gradient
        return create_args(model, gamma or 0.95, lrate or 0.001, None,
                           episode_len or 10, batch_size or 100, 1000,
                           decay=(decay or 0),
                           segment_input=segmentation_input,
                           depth_input=depth_input,
                           resolution_level=resolution_level)
    elif (algo == 'a2c') or (algo == 'a3c') or  (algo == 'dqn') or (algo == 'qac'):  # a2c/a3c, discrete action space
        return create_args(model, gamma or 0.95, lrate or 0.001,
                           episode_len = episode_len or 50,
                           batch_size = batch_size or 256,
                           replay_buffer_size = replay_buffer_size or int(100000),
                           update_freq=(update_freq or 50),
                           use_batch_norm=use_batch_norm,
                           entropy_penalty=entropy_penalty,
                           critic_penalty=critic_penalty,
                           decay=(decay or 0),
                           rnn_layers=(rnn_layers or 1),
                           rnn_cell=(rnn_cell or 'lstm'),
                           rnn_units=(rnn_units or 64),
                           segment_input=segmentation_input,
                           depth_input=depth_input,
                           resolution_level=resolution_level)
    elif 'ddpg' in algo:  # ddpg
        attention_resolution = attention_resolution_dict[att_resolution_level]
        return create_args(model, gamma or 0.95, lrate or 0.001, critic_lrate or 0.001,
                           episode_len or 50,
                           batch_size or 256,
                           replay_buffer_size or int(5e5),
                           update_freq=(update_freq or 50),
                           use_batch_norm=use_batch_norm,
                           entropy_penalty=entropy_penalty,
                           critic_penalty=critic_penalty,
                           decay=(decay or 0), critic_decay=(critic_decay or 0),
                           segment_input=segmentation_input,
                           depth_input=depth_input,
                           resolution_level=resolution_level,
                           # attention params
                           att_resolution=attention_resolution,
                           att_skip=(1 if ('attentive' in model) and depth_input and att_skip_depth else 0))
    elif algo == 'rdpg':  # rdpg
        return create_args(model, gamma or 0.95, lrate or 0.001, critic_lrate or 0.001,
                           episode_len or 50,
                           batch_size or 64,
                           replay_buffer_size or int(20000),
                           use_batch_norm=use_batch_norm,
                           entropy_penalty=entropy_penalty,
                           critic_penalty=critic_penalty,
                           decay=(decay or 0), critic_decay=(critic_decay or 0),
                           batch_len=(batch_len or 20),
                           rnn_layers=(rnn_layers or 1),
                           rnn_cell=(rnn_cell or 'lstm'),
                           rnn_units=(rnn_units or 64),
                           segment_input=segmentation_input,
                           depth_input=depth_input,
                           resolution_level=resolution_level)
    elif algo == 'nop':
        return create_args(segment_input=segmentation_input,
                           depth_input=depth_input,
                           resolution_level=resolution_level)
    else:
        assert (False)


def create_policy(args, inp_shape, act_shape, name='cnn'):
    use_bc = args['use_batch_norm']
    if name == 'random':
        policy = RandomPolicy(act_shape)
    elif name == 'cnn':
        # assume CNN Policy
        policy = CNNPolicy(inp_shape, act_shape,
                        hiddens=[32, 64, 128, 128],
                        linear_hiddens=[128, 64],
                        kernel_sizes=5, strides=2,
                        activation=F.relu,  # F.relu
                        use_batch_norm=use_bc)  # False
    elif name == 'rnn':
        # use RNN Policy
        policy = RNNPolicy(inp_shape, act_shape,
                        conv_hiddens=[32, 64, 128, 128],
                        linear_hiddens=[64],
                        kernel_sizes=5, strides=2,
                        rnn_cell=args['rnn_cell'],
                        rnn_layers=args['rnn_layers'],
                        rnn_units=args['rnn_units'],
                        activation=F.relu,  # F.relu
                        use_batch_norm=use_bc,
                        batch_norm_after_rnn=False)
    else:
        assert False, 'Policy Undefined for <{}>'.format(name)
    if use_cuda:
        policy.cuda()
    return policy


def create_critic(args, inp_shape, act_shape, model, extra_dim=0):
    use_bc = args['use_batch_norm']
    act_dim = act_shape if isinstance(act_shape, int) else sum(act_shape)
    act_dim += extra_dim
    if model == 'gate-cnn':
        if args['residual_critic']:
            critic = DDPGCritic(inp_shape, act_dim,
                                conv_hiddens=[32, 32, 32, 64, 64, 64, 128, 128, 128],
                                kernel_sizes=[5, 3, 3, 3, 3, 3, 3, 3, 3],
                                strides=[2, 1, 1, 2, 1, 1, 2, 1, 2],
                                transform_hiddens=[32, 256],
                                linear_hiddens=[256, 64],
                                use_action_gating=True,
                                activation=F.relu,  # F.elu
                                use_batch_norm=use_bc)
        else:
            critic = DDPGCritic(inp_shape, act_dim,
                                conv_hiddens=[32, 64, 128, 128],
                                transform_hiddens=[32, 256],
                                linear_hiddens=[256, 64],
                                use_action_gating=True,
                                activation=F.relu,  # F.elu
                                use_batch_norm=use_bc)
    elif model == 'cnn':
        critic = DDPGCritic(inp_shape, act_dim,
                            conv_hiddens=[32, 64, 128, 128],
                            linear_hiddens=[256],
                            activation=F.relu,  # F.elu
                            use_batch_norm=use_bc)
    elif model == 'rnn':
        critic = RNNCritic(inp_shape, act_dim,
                           conv_hiddens=[32, 64, 128, 128],
                           linear_hiddens=[64],
                           rnn_cell=args['rnn_cell'],
                           rnn_layers=args['rnn_layers'],
                           rnn_units=args['rnn_units'],
                           activation=F.relu,  # F.elu
                           use_batch_norm=use_bc)
    else:
        assert False, 'No critic defined for model<{}>'.format(model)
    if use_cuda:
        critic.cuda()
    return critic


def create_joint_model(args, inp_shape, act_shape):
    use_bc = args['use_batch_norm']
    name = args['model_name']
    if args['resolution_level'] in ['normal', 'square', 'high']:
        cnn_hiddens = [64, 64, 128, 128]
        kernel_sizes = 5
        strides = 2
    elif args['resolution_level'] in ['low', 'tiny', 'square_low']:
        cnn_hiddens = [64, 64, 128, 256, 512]
        kernel_sizes = [5, 3, 3, 3, 3]
        strides = [1, 2, 2, 2, 2]
    else:
        assert False, 'resolution level <{}> not supported!'.format(args['resolution_level'])

    if not args['action_gating']:
        transform_hiddens = []
        policy_hiddens=[]
        critic_hiddens=[100, 32]
    else:
        transform_hiddens=[32, 128]
        critic_hiddens=[128,64]
        policy_hiddens=[64]

    if name == 'cnn':
        model = JointModel(inp_shape, act_shape,
                           cnn_hiddens=cnn_hiddens,
                           linear_hiddens=[512],
                           policy_hiddens=policy_hiddens,
                           transform_hiddens=transform_hiddens,
                           critic_hiddens=critic_hiddens,
                           kernel_sizes=kernel_sizes,
                           strides=strides,
                           activation=F.relu,  # F.relu
                           use_action_gating=args['action_gating'],
                           use_batch_norm=use_bc,
                           multi_target=args['multi_target'],
                           use_target_gating=args['target_gating'])
    elif name == 'attentive_cnn':
        assert not args['multi_target'], 'Attentive Model currently does not support Multi-Target Training'
        global single_observation_shape
        model = AttJointModel(inp_shape, act_shape,
                              cnn_hiddens=cnn_hiddens,
                              linear_hiddens=[512],
                              policy_hiddens=policy_hiddens,
                              transform_hiddens=transform_hiddens,
                              critic_hiddens=critic_hiddens,
                              kernel_sizes=kernel_sizes,
                              strides=strides,
                              activation=F.relu,  # F.relu
                              use_action_gating=args['action_gating'],
                              use_batch_norm=use_bc,
                              attention_dim=args['att_resolution'],
                              shared_cnn=args['att_shared_cnn'],
                              attention_chn=single_observation_shape[0],
                              attention_skip=args['att_skip'],
                              attention_hiddens=[128]
                             )
    else:
        assert False, 'model name <{}> not supported'.format(name)

    print('create joint model <{}>!!!! cuda = {}'.format(name, use_cuda))
    if use_cuda:
        model.cuda()
    return model

def create_discrete_model(algo, args, inp_shape):
    use_bc = args['use_batch_norm']
    if args['multi_target']:
        assert algo in ['dqn'], '[Error] Multi-Target Learning only supports <DQN> and <Recurrent-A3C>'
    if (algo == 'a2c') or (algo == 'a3c'):
        model = A2CModel(inp_shape, n_discrete_actions,
                         cnn_hiddens=[64, 64, 128, 128],
                         linear_hiddens=[512],
                         critic_hiddens=[100, 32],
                         act_hiddens=[100, 32],
                         activation=F.relu,
                         use_batch_norm=use_bc)
    elif algo == 'qac':
        model = QACModel(inp_shape, n_discrete_actions,
                         cnn_hiddens=[32, 64, 128, 128],
                         linear_hiddens=[512],
                         critic_hiddens=[256, 32],
                         act_hiddens=[256, 32],
                         activation=F.relu, use_batch_norm=use_bc,
                         multi_target=args['multi_target'],
                         use_target_gating=args['target_gating'])
    elif algo == 'dqn':
        model = QACModel(inp_shape, n_discrete_actions,
                         cnn_hiddens=[32, 64, 128, 128],
                         linear_hiddens=[512],
                         critic_hiddens=[256, 32],
                         activation=F.relu, use_batch_norm=use_bc,
                         only_q_network=True)
    else:
        assert False, 'algo name <{}> currently not supported!'.format(algo)
    if use_cuda:
        model.cuda()
    return model

def create_trainer(algo, model, args):
    if ('multi_target' in args) and args['multi_target']:
        assert algo in ['ddpg_joint', 'dqn', 'nop'], '[Error] Multi-Target Training only support for <ddpg_joint> and <dqn>'
    if algo == 'pg':
        policy = create_policy(args, observation_shape, action_shape,
                               name=model)
        trainer = PGTrainer('PolicyGradientTrainer', policy,
                            observation_shape, action_shape, args)
    elif algo == 'nop':
        policy = create_policy(args, observation_shape, action_shape,
                               name=model)
        trainer = NOPTrainer('NOPTrainer', policy, observation_shape, action_shape, args)
    elif algo == 'ddpg':
        assert(model == 'cnn')
        critic_gen = lambda: create_critic(args, observation_shape, action_shape, 'cnn')
        policy_gen = lambda: create_policy(args, observation_shape, action_shape, 'cnn')
        trainer = DDPGTrainer('DDPGTrainer', policy_gen, critic_gen,
                              observation_shape, action_shape, args)
    elif algo == 'ddpg_eagle':
        eagle_shape = (4, default_eagle_resolution, default_eagle_resolution)
        critic_gen = lambda: create_critic(args, eagle_shape, action_shape, 'gate-cnn', extra_dim=4)  # need to input direction info
        policy_gen = lambda: create_policy(args, observation_shape, action_shape, 'cnn')
        trainer = EagleDDPGTrainer('EagleDDPGTrainer', policy_gen, critic_gen,
                                   observation_shape, eagle_shape, action_shape, args)
    elif (algo == 'ddpg_joint') or (algo == 'ddpg_alter'):
        assert('cnn' in model)
        model_gen = lambda: create_joint_model(args, observation_shape, action_shape)
        Trainer = JointTrainer if algo == 'ddpg_joint' else AlterTrainer
        trainer = Trainer('JointDDPGTrainer', model_gen,
                           observation_shape, action_shape, args)
    elif algo == 'rdpg':
        # critic can be either "cnn" or "rnn"
        critic_gen = lambda: create_critic(args, single_observation_shape, action_shape, model)
        policy_gen = lambda: create_policy(args, single_observation_shape, action_shape, 'rnn')
        trainer = RDPGTrainer('RDPGTrainer', policy_gen, critic_gen,
                              single_observation_shape, action_shape, args)
    elif algo == 'a2c':
        model_gen = lambda: create_discrete_model(algo, args, observation_shape)
        trainer = A2CTrainer('A2CTrainer', model_gen,
                             observation_shape,
                             n_discrete_actions, args)
    elif algo == 'qac':
        model_gen = lambda: create_discrete_model(algo, args, observation_shape)
        trainer = QACTrainer('QACTrainer', model_gen, observation_shape,
                             n_discrete_actions, args)
    elif algo == 'dqn':
        model_gen = lambda: create_discrete_model(algo, args, observation_shape)
        trainer = DQNTrainer('DQNTrainer', model_gen, observation_shape,
                             n_discrete_actions, args)
    else:
        assert False, 'Trainer not defined for <{}>'.format(algo)
    return trainer


def create_house(houseID, genRoomTypeMap=False, cacheAllTarget=False, includeOutdoor=True):
    objFile = prefix + houseID + '/house.obj'
    jsonFile = prefix + houseID + '/house.json'
    cachedFile = genCacheFile(houseID)
    #if not os.path.isfile(cachedFile):
    #    assert False, 'No Cache File Found! file={}'.format(cachedFile)
    #    print('Generating Cached Map File for House <{}>!'.format(houseID))
    #    house = House(jsonFile, objFile, csvFile,
    #                  MapTargetCatFile=modelObjectMapFile,
    #                  StorageFile=cachedFile, GenRoomTypeMap=genRoomTypeMap,
    #                  IncludeOutdoorTarget=True)
    #else:
    house = House(jsonFile, objFile, csvFile,
                      MapTargetCatFile=modelObjectMapFile,
                      CachedFile=cachedFile, GenRoomTypeMap=genRoomTypeMap,
                      IncludeOutdoorTarget=includeOutdoor)
    #house = House(jsonFile, objFile, csvFile,
    #              ColideRes=colide_res,
    #              CachedFile=cachedFile, EagleViewRes=default_eagle_resolution,
    #              GenRoomTypeMap=genRoomTypeMap)
    if cacheAllTarget:
        house.cache_all_target()
    return house

def create_house_from_index(k, genRoomTypeMap=False, cacheAllTarget=False, includeOutdoor=True):
    if k >= 0:
        if k >= len(all_houseIDs):
            print('k={} exceeds total number of houses ({})! Randomly Choose One!'.format(k, len(all_houseIDs)))
            houseID = random.choice(all_houseIDs)
        else:
            houseID = all_houseIDs[k]
        return create_house(houseID, genRoomTypeMap, cacheAllTarget, includeOutdoor=includeOutdoor)
    else:
        k = -k
        print('Multi-House Environment! Total Selected Houses = {}'.format(k))
        if k > len(all_houseIDs):
            print('  >> k={} exceeds total number of houses ({})! use all houses!'.format(k, len(all_houseIDs)))
            k = len(all_houseIDs)
        import time
        ts = time.time()
        print('Caching All Worlds ...')
        # use the first k houses
        ret_worlds = []
        if flag_parallel_init:
            from multiprocessing import Pool
            _args = [(all_houseIDs[j], genRoomTypeMap, cacheAllTarget, includeOutdoor) for j in range(k)]
            #with Pool(min(50, k)) as pool:
            with Pool(k) as pool:
                ret_worlds = pool.starmap(create_house, _args)  # parallel version for initialization
        else:
            ret_worlds = [create_house(all_houseIDs[j], genRoomTypeMap, cacheAllTarget, includeOutdoor) for j in range(k)]
        print('  >> Done! Time Elapsed = %.4f(s)' % (time.time() - ts))
        return ret_worlds
        # return [create_world(houseID, genRoomTypeMap) for houseID in all_houseIDs[:k]]

def create_env(k=0,
               hardness=None, max_birthplace_steps=None,
               reward_type='new', success_measure='see',
               segment_input='color', depth_input=True,
               max_steps=-1,
               render_device=None,
               genRoomTypeMap=False,
               cacheAllTarget=False,
               use_discrete_action=True,
               include_object_target=False,
               reward_silence=0,
               curriculum_schedule=None,
               target_mask_input=False,
               task_name='roomnav',
               false_rate=0.0,
               discrete_angle=True,
               cache_supervision=False,
               include_outdoor_target=True,
               min_birthplace_grids=1,
               cache_discrete_angles=False,
               multithread_api=False):
    """
    :param k: the index of house to generate
        when k < 0, it menas the first |k| houses from the environment set
        make sure you have called *set_house_IDs()* to select the desired house set (default the small set of 20 houses)
    :param hardness: a real value [0, 1] indicating the maximum hardness of the task, None means 1.0
        the birthplace of the agent will be at most (hardness * house_diameter) to the target
    :param max_birthplace_steps: the maximum meters that the agent will be spawned from the target
        when None, the birthplace of the agent can be anywhere in the house
    :param min_birthplace_grids: the minimum number of *grids* between agents the birthplace and target rooms
        default 1, so agents will be always outside target regions
    :param reward_type: use 'new' by default
    :param success_measure: use 'see' by default.
        If you want the agent to terminate the episode by itself, use 'see-stop'.
    :param segment_input: set 'none' to not include segmentation input
    :param depth_input: whether to include depth signal
    :param max_steps: maximum steps to terminate the episode, -1 means never
    :param render_device: the GPU id to render the environment
        NOTE: this may NOT be the same as the GPU index from nvidia-smi (CUDA)
    :param genRoomTypeMap: whether to generate room type map on the fly
    :param cacheAllTarget: whether to cache all target metadata; recommend True if the target is not fixed
    :param use_discrete_action: MUST be true for LSTM policy
    :param include_object_target: whether to include object type as navigation targets
    :param reward_silence: default 0, the number of steps in the beginning of episode without rewards
    :param curriculum_schedule: schedule of curriculum, default None
        check the comments in the RoonNavTask class for details
    :param target_mask_input: whether to include a 0/1 mask indicating whether each pixel belongs to the target type
    :param task_name: default roomnav
    :param false_rate: default 0.0
    :param discrete_angle: when True, the possible rotation angle of the agent will be discretized
    :param cache_supervision: default false, option for DAgger
    :param include_outdoor_target: default true, whether to include outdoor as targets
    :param cache_discrete_angles: default false, for DAgger
    :param multithread_api: whether to use thread safe renderer API
    :return: a RoomNavTask environment instance
    """
    if render_device is None:
        render_device = get_gpus_for_rendering()[0]   # by default use the first gpu
    if segment_input is None:
        segment_input = 'none'
    if multithread_api:
        api = objrender.RenderAPIThread(w=resolution[0], h=resolution[1], device=render_device)
    else:
        api = objrender.RenderAPI(w=resolution[0], h=resolution[1], device=render_device)
    if cache_supervision:
        assert discrete_angle and use_discrete_action
        cacheAllTarget = True
    if isinstance(k, tuple):  # a range of houses
        assert (len(k) == 2) and (k[0] < k[1]) and (k[0] >= 0)
        all_houses = [create_house_from_index(i, genRoomTypeMap, cacheAllTarget, include_outdoor_target) for i in range(k[0], k[1])]
        env = MultiHouseEnv(api, all_houses, config=CFG)
    elif k >= 0:
        house = create_house_from_index(k, genRoomTypeMap, cacheAllTarget, include_outdoor_target)
        env = HouseEnv(api, house, config=CFG)
    else:  # multi-house environment
        all_houses = create_house_from_index(k, genRoomTypeMap, cacheAllTarget, include_outdoor_target)
        env = MultiHouseEnv(api, all_houses, config=CFG)
    Task = RoomNavTask if task_name == 'roomnav' else ObjNavTask
    task = Task(env, reward_type=reward_type,
                hardness=hardness, max_birthplace_steps=max_birthplace_steps,
                segment_input=(segment_input != 'none'),
                joint_visual_signal=(segment_input == 'joint'),
                depth_signal=depth_input,
                target_mask_signal=target_mask_input,
                max_steps=max_steps, success_measure=success_measure,
                discrete_action=use_discrete_action,
                include_object_target=include_object_target,
                reward_silence=reward_silence,
                birthplace_curriculum_schedule=curriculum_schedule,
                false_rate=false_rate,
                discrete_angle=discrete_angle,
                supervision_signal=cache_supervision,
                min_birth_grid_dist=min_birthplace_grids,
                cache_discrete_angles=cache_discrete_angles)
    return task


def get_gpus_for_rendering():
    """
    Returns:
        list of int. The device ids that can be used for RenderAPI
    """
	# to respect env var
    if 'CUDA_VISIBLE_DEVICES' not in os.environ:
        return [0]  # default setting
    return list(map(int, os.environ['CUDA_VISIBLE_DEVICES'].split(',')))
