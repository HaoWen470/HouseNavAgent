#!/bin/bash

CUDA_VISIBLE_DEVICES=1,2 python3 zmq_train.py --seed 0 --env-set small \
    --n-house 3 --n-proc 5 --batch-size 5 --t-max 25 --max-episode-len 100 \
    --hardness 0.95 --reward-type delta --success-measure see \
    --multi-target --use-target-gating \
    --segmentation-input color --depth-input --resolution normal \
    --render-gpu 0,1 --max-iters 100000 \
    --algo a3c --lrate 0.001 --weight-decay 0.00001 --gamma 0.95 --batch-norm \
    --entropy-penalty 0.1 --q-loss-coef 1.0 --grad-clip 1.0 \
    --rnn-units 256 --rnn-layers 1 --rnn-cell lstm \
    --report-rate 20 --save-rate 1000 --eval-rate 200000 \
    --save-dir ./_model_/icml/tmp \
    --log-dir ./log/icml/tmp

