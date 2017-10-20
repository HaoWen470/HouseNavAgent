#!/bin/bash

CUDA_VISIBLE_DEVICES=3 python3 train.py --env-set small --seed 0 --algo ddpg_joint --update-freq 5 --max-episode-len 100 \
    --house -20 --reward-type delta --success-measure see \
    --lrate 0.0001 --gamma 0.95 \
    --save-dir ./_model_/multi_house/delta_reward/segcolor_depth_20house_hard/ddpg_joint_100_exp_high_hist_3_new \
    --log-dir ./log/multi_house/delta_reward/segcolor_depth_20house_hard/ddpg_joint_100_exp_high_hist_3_new \
    --batch-size 256 --hardness 0.95 --replay-buffer-size 700000 \
    --weight-decay 0.00001 --critic-penalty 0.0001 --entropy-penalty 0.01 \
    --batch-norm --no-debug \
    --noise-scheduler high --q-loss-coef 100 --use-action-gating \
    --segmentation-input color --depth-input --resolution normal --history-frame-len 3
