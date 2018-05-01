import os, sys
import pickle
import numpy as np
from config import get_config

CFG = get_config()

time_counter = [0,0,0,0]

n_segmentation_mask = 20  # including unknown, it is 21, we set unknown as 0

if CFG.get('python_path'):
    sys.path.insert(0, CFG['python_path'])
import House3D

import torch
from torch.autograd import Variable

use_cuda = torch.cuda.is_available()
if use_cuda:
    print('>>> CUDA used!!!')
FloatTensor = torch.cuda.FloatTensor if use_cuda else torch.FloatTensor
IntTensor = torch.cuda.IntTensor if use_cuda else torch.IntTensor
LongTensor = torch.cuda.LongTensor if use_cuda else torch.LongTensor
ByteTensor = torch.cuda.ByteTensor if use_cuda else torch.ByteTensor
Tensor = FloatTensor

# define AgentTrainer Template
class AgentTrainer(object):
    def __init__(self):
        self.cachedFrames = None
        self.cachedSingleFrame = None

    def reset_agent(self):
        pass

    def action(self, obs):
        raise NotImplemented()

    def process_observation(self, obs):
        raise NotImplemented()

    def process_experience(self, idx, act, rew, done, terminal, info):
        raise NotImplemented()

    def preupdate(self):
        raise NotImplemented()

    def update(self):
        raise NotImplemented()

    def _process_frames(self, raw_frames, volatile=False, merge_dim=True, return_variable=True):
        """
        frames: (batch_size, len, n, m, channel_n) in numpy
        output:
        >> merge_dim=True: (batch_size, len * channel_n, n, m), processed as FloatTensor
           merge_dim=False:(batch_size, len, channel_n, n, m), processed as FloatTensor
        """
        if len(raw_frames.shape) == 4:  # frame_history_len == 1
            raw_frames = raw_frames[:,np.newaxis,:,:,:]

        batch_size = raw_frames.shape[0]
        img_h, img_w = raw_frames.shape[2], raw_frames.shape[3]

        if self.args['segment_input'] == 'index':
            assert not self.args['depth_input'], '[Trainer Error] Currently do not support <index> + <depth> as input!'
            seq_len = raw_frames.shape[1]
            if (batch_size > 1) and (self.cachedFrames is None):
                self.cachedFrames = frames = \
                    torch.zeros(batch_size, seq_len, img_h, img_w,
                                n_segmentation_mask).type(FloatTensor)
            elif (batch_size == 1) and (self.cachedSingleFrame is None):
                self.cachedSingleFrame = frames = \
                    torch.zeros(batch_size, seq_len, img_h, img_w,
                                n_segmentation_mask).type(FloatTensor)
            else:
                frames = self.cachedFrames if batch_size > 1 else self.cachedSingleFrame
                frames.zero_()
            indexes = torch.from_numpy(raw_frames).type(ByteTensor)
            src = (indexes < n_segmentation_mask).type(ByteTensor).type(FloatTensor)
            indexes=indexes.type(LongTensor)
            frames.scatter_(-1,indexes,src)
            chn = seq_len * n_segmentation_mask
        else:
            chn = raw_frames.shape[1] * raw_frames.shape[4]
            frames = torch.from_numpy(raw_frames).type(ByteTensor)
        if return_variable:
            frames = Variable(frames, volatile=volatile)
        frames = frames.permute(0, 1, 4, 2, 3)
        if merge_dim: frames = frames.resize(batch_size, chn, img_h, img_w)
        if self.args['segment_input'] != 'index':
            if self.args['depth_input'] or ('attentive' in self.args['model_name']):
                frames = frames.type(FloatTensor) / 256.0  # special hack here for depth info
            else:
                frames = (frames.type(FloatTensor) - 128.0) / 128.0
        return frames

    def eval(self):
        self.policy.eval()

    def train(self):
        self.policy.train()

    def save(self, save_dir, version="", target_dict_data=None):
        if len(version) > 0:
            version = "_" + version
        if save_dir[-1] != '/':
            save_dir += '/'
        if target_dict_data is None:
            filename = save_dir + self.name + version + '.pkl'
            torch.save(self.policy.state_dict(), filename)
        else:
            filename = save_dir + self.name + version + '.pkl'
            with open(filename, 'wb') as fp:
                pickle.dump(target_dict_data, fp)

    def load(self, save_dir, version=""):
        if os.path.isfile(save_dir) or (version is None):
            filename = save_dir
        else:
            if len(version) > 0:
                version = "_" + version
            if save_dir[-1] != '/':
                save_dir += '/'
                filename = save_dir + self.name + version + '.pkl'
        if os.path.exists(filename):
            self.policy.load_state_dict(torch.load(filename, map_location=lambda storage, loc: storage))
        else:
            print('[Warning] model file not found! loading skipped... target = <{}>'.format(filename))

    def is_rnn(self):
        return False


class BaseMotion(object):
    def __init__(self, task, trainer):
        self.task = task
        self.trainer = trainer

    """
    return a list of [aux_mask, action, reward, done]
    """
    def run(self, target, max_steps):
        pass