#!/bin/bash

CUDA_VISIBLE_DEVICES=3,4,5,6,7 python3 zmq_train.py --job-name large \
    --seed 0 --env-set train --rew-clip 3 \
    --n-house 200 --n-proc 200 --batch-size 64 --t-max 30 --grad-batch 1  \
    --max-episode-len 40 \
    --hardness 0.95 --max-birthplace-steps 5 --min-birthplace-grids 2 \
    --reward-type new --success-measure see \
    --multi-target --use-target-gating \
    --include-mask-feature \
    --segmentation-input color --depth-input --resolution normal \
    --render-gpu 1,2,3,4 --max-iters 100000 \
    --algo a3c --lrate 0.001 --weight-decay 0.00001 --gamma 0.98 --batch-norm \
    --entropy-penalty 0.05 --logits-penalty 0.01 --q-loss-coef 1.0 --grad-clip 1.0 --adv-norm \
    --rnn-units 256 --rnn-layers 1 --rnn-cell lstm \
    --report-rate 20 --save-rate 1000 --eval-rate 300000 \
    --save-dir ./_model_/nips/baseline/room_seg \
    --log-dir ./log/nips/baseline/room_seg