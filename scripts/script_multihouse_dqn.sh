#!/bin/bash

CUDA_VISIBLE_DEVICES=2 python train.py --seed 0 --algo dqn --update-freq 3 --max-episode-len 100 \
    --house -20 --reward-type delta --success-measure see \
    --lrate 0.001 --gamma 0.95 \
    --save-dir ./_model_/multi_house/20house_hard/delta_segcolor_dqn_eplen100_exp_exp \
    --log-dir ./log/multi_house/20house_hard/delta_segcolor_dqn_eplen100_exp_exp \
    --batch-size 256 --hardness 0.95 --replay-buffer-size 1000000 \
    --weight-decay 0.00001 \
    --batch-norm --no-debug \
    --noise-scheduler exp \
    --segmentation-input color --depth-input --resolution normal --history-frame-len 3
