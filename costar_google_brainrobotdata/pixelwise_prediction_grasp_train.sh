export CUDA_VISIBLE_DEVICES="0" && python2 grasp_train.py --batch_size=7 --epochs 300 --save_weights delta_depth_sin_cos_3 --grasp_model grasp_model_levine_2016_segmentation --optimizer SGD