#!/bin/bash

CUDA_VISIBLE_DEVICES=3 python train.py --algo rdpg --seed 0 \
    --house 0 --linear-reward \
    --rnn-cell gru --rnn-units 100 --rnn-layers 1 \
    --lrate 0.001 --critic-lrate 0.001 --gamma 0.95 \
    --save-dir ./_model_/rnn/linear_reward/hard/long_rdpg_cnn_critic \
    --log-dir ./log/rnn/linear_reward/hard/long_rdpg_cnn_critic \
    --max-episode-len 100 --replay-buffer-size 30000 \
    --batch-size 128 --batch-length 35 --hardness 0.95 \
    --critic-weight-decay 0.000001 --critic-penalty 0.0001 --batch-norm \
    --no-debug