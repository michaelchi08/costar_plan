import os
import datetime
import numpy as np
import tensorflow as tf
import keras
from keras import backend as K
from keras.applications.imagenet_utils import preprocess_input

from keras.callbacks import ReduceLROnPlateau
from keras.callbacks import CSVLogger
from keras.callbacks import EarlyStopping
from keras.callbacks import ModelCheckpoint
import grasp_dataset
import grasp_model

from tensorflow.python.platform import flags


tf.flags.DEFINE_string('grasp_model', 'grasp_model_single',
                       """Choose the model definition to run, options are grasp_model and grasp_model_segmentation""")
tf.flags.DEFINE_string('save_weights', 'grasp_model_weights.h5',
                       """Save a file with the trained model weights.""")
tf.flags.DEFINE_string('load_weights', 'grasp_model_weights.h5',
                       """Load and continue training the specified file containing model weights.""")
tf.flags.DEFINE_integer('epochs', 100,
                        """Epochs of training""")
tf.flags.DEFINE_integer('random_crop_width', 472,
                        """Width to randomly crop images, if enabled""")
tf.flags.DEFINE_integer('random_crop_height', 472,
                        """Height to randomly crop images, if enabled""")
tf.flags.DEFINE_boolean('random_crop', False,
                        """random_crop will apply the tf random crop function with
                           the parameters specified by random_crop_width and random_crop_height
                        """)
tf.flags.DEFINE_integer('resize_width', 80,
                        """Width to resize images, if enabled""")
tf.flags.DEFINE_integer('resize_height', 64,
                        """Height to resize images, if enabled""")
tf.flags.DEFINE_boolean('resize', True,
                        """resize will resize the input images to the desired dimensions specified but the
                           resize_width and resize_height flags. It is suggested that an exact factor of 2 be used
                           relative to the input image directions if random_crop is disabled or the crop dimensions otherwise.
                        """)
tf.flags.DEFINE_boolean('image_augmentation', False,
                        'image augmentation applies random brightness, saturation, hue, contrast')
tf.flags.DEFINE_boolean('imagenet_mean_subtraction', True,
                        'subtract the imagenet mean pixel values from the rgb images')
tf.flags.DEFINE_integer('grasp_sequence_max_time_steps', None,
                        """The grasp motion time sequence consists of up to 11 time steps.
                           This integer, or None for unlimited specifies the max number of these steps from the last to the first
                           that will be used in training. This may be needed to reduce memory utilization.
                           TODO(ahundt) use all time steps in all situations.""")
# tf.flags.DEFINE_integer('batch_size', 1,
#                         """size of a single batch during training""")

FLAGS = flags.FLAGS


# http://stackoverflow.com/a/5215012/99379
def timeStamped(fname, fmt='%Y-%m-%d-%H-%M-%S_{fname}'):
    return datetime.datetime.now().strftime(fmt).format(fname=fname)


class GraspTrain(object):

    @staticmethod
    def _image_augmentation(image, num_channels=None):
        """Performs data augmentation by randomly permuting the inputs.

        TODO(ahundt) should normalization be applied first, or make sure values are 0-255 here, even in float mode?

        Source: https://github.com/tensorflow/models/blob/aed6922fe2da5325bda760650b5dc3933b10a3a2/domain_adaptation/pixel_domain_adaptation/pixelda_preprocess.py#L81

        Args:
            image: A float `Tensor` of size [height, width, channels] with values
            in range[0,1].
        Returns:
            The mutated batch of images
        """
        # Apply photometric data augmentation (contrast etc.)
        if num_channels is None:
            num_channels = image.shape()[-1]
        if num_channels == 4:
            # Only augment image part
            image, depth = image[:, :, 0:3], image[:, :, 3:4]
        elif num_channels == 1:
            image = tf.image.grayscale_to_rgb(image)
        image = tf.image.random_brightness(image, max_delta=0.1)
        image = tf.image.random_saturation(image, lower=0.5, upper=1.5)
        image = tf.image.random_hue(image, max_delta=0.032)
        image = tf.image.random_contrast(image, lower=0.5, upper=1.5)
        image = tf.clip_by_value(image, 0, 1.0)
        if num_channels == 4:
            image = tf.concat(2, [image, depth])
        elif num_channels == 1:
            image = tf.image.rgb_to_grayscale(image)
        return image

    @staticmethod
    def _imagenet_mean_subtraction(tensor):
        """Do imagenet preprocessing, but make sure the network you are using needs it!

           zero centers by mean pixel.
        """
        # TODO(ahundt) do we need to divide by 255 to make it floats from 0 to 1? It seems no based on https://keras.io/applications/
        # TODO(ahundt) apply resolution to https://github.com/fchollet/keras/pull/7705 when linked PR is closed
        # TODO(ahundt) also apply per image standardization?
        pixel_value_offset = tf.constant([103.939, 116.779, 123.68])
        return tf.subtract(tensor, pixel_value_offset)

    def _rgb_preprocessing(self, rgb_image_op,
                           image_augmentation=FLAGS.image_augmentation,
                           imagenet_mean_subtraction=FLAGS.imagenet_mean_subtraction,
                           random_crop=FLAGS.random_crop,
                           resize=FLAGS.resize):
        """Preprocess an rgb image into a float image, applying image augmentation and imagenet mean subtraction if desired.

           WARNING: do not use if you are processing depth images in addition to rgb, the random crop dimeions won't match up!
        """
        with tf.name_scope('rgb_preprocessing') as scope:
            # make sure the shape is correct
            rgb_image_op = tf.squeeze(rgb_image_op)
            # apply image augmentation and imagenet preprocessing steps adapted from keras
            if random_crop:
                rgb_image_op = tf.random_crop(rgb_image_op,
                                              tf.constant([FLAGS.random_crop_height, FLAGS.random_crop_width, 3],
                                                          name='random_crop_height_width'))
            if resize:
                rgb_image_op = tf.image.resize_images(rgb_image_op,
                                                      tf.constant([FLAGS.resize_height, FLAGS.resize_width],
                                                                  name='resize_height_width'))
            if image_augmentation:
                rgb_image_op = GraspTrain._image_augmentation(rgb_image_op, num_channels=3)
            rgb_image_op = tf.cast(rgb_image_op, tf.float32)
            if imagenet_mean_subtraction:
                rgb_image_op = GraspTrain._imagenet_mean_subtraction(rgb_image_op)
            return tf.cast(rgb_image_op, tf.float32)

    def train(self, dataset=FLAGS.grasp_dataset, batch_size=FLAGS.batch_size, epochs=FLAGS.epochs,
              load_weights=FLAGS.save_weights,
              save_weights=FLAGS.load_weights,
              make_model_fn=grasp_model.grasp_model,
              imagenet_mean_subtraction=FLAGS.imagenet_mean_subtraction,
              grasp_sequence_max_time_steps=FLAGS.grasp_sequence_max_time_steps,
              random_crop=FLAGS.random_crop,
              resize=FLAGS.resize,
              resize_height=FLAGS.resize_height,
              resize_width=FLAGS.resize_width):
        """Train the grasping dataset

        This function depends on https://github.com/fchollet/keras/pull/6928

        # Arguments

            make_model_fn:
                A function of the form below which returns an initialized but not compiled model, which should expect
                input tensors.

                    make_model_fn(pregrasp_op_batch,
                                  grasp_step_op_batch,
                                  simplified_grasp_command_op_batch)

            grasp_sequence_max_time_steps: number of motion steps to train in the grasp sequence,
                this affects the memory consumption of the system when training, but if it fits into memory
                you almost certainly want the value to be None, which includes every image.
        """
        data = grasp_dataset.GraspDataset(dataset=dataset)
        # list of dictionaries the length of batch_size
        feature_op_dicts, features_complete_list, num_samples = data.get_simple_parallel_dataset_ops(batch_size=batch_size)
        # TODO(ahundt) https://www.tensorflow.org/performance/performance_models
        # make sure records are always ready to go
        # staging_area = tf.contrib.staging.StagingArea()

        # TODO(ahundt) make "batches" also contain additional steps in the grasp attempt
        rgb_clear_view = data.get_time_ordered_features(
            features_complete_list,
            feature_type='/image/decoded',
            step='view_clear_scene'
        )

        rgb_move_to_grasp_steps = data.get_time_ordered_features(
            features_complete_list,
            feature_type='/image/decoded',
            step='move_to_grasp'
        )

        pose_op_params = data.get_time_ordered_features(
            features_complete_list,
            feature_type='params',
            step='move_to_grasp'
        )

        # print('features_complete_list: ', features_complete_list)
        grasp_success = data.get_time_ordered_features(
            features_complete_list,
            feature_type='grasp_success'
        )
        # print('grasp_success: ', grasp_success)

        # TODO(ahundt) Do we need to add some imagenet preprocessing here? YES when using imagenet pretrained weights
        # TODO(ahundt) THE NUMBER OF GRASP STEPS MAY VARY... CAN WE DEAL WITH THIS? ARE WE?

        # our training batch size will be batch_size * grasp_steps
        # because we will train all grasp step images w.r.t. final
        # grasp success result value
        pregrasp_op_batch = []
        grasp_step_op_batch = []
        # simplified_network_grasp_command_op
        simplified_grasp_command_op_batch = []
        grasp_success_op_batch = []
        # go through every element in the batch
        for fixed_feature_op_dict, sequence_feature_op_dict in feature_op_dicts:
            # print('fixed_feature_op_dict: ', fixed_feature_op_dict)
            # get the pregrasp image, and squeeze out the extra batch dimension from the tfrecord
            # TODO(ahundt) move squeeze steps into dataset api if possible
            pregrasp_image_rgb_op = fixed_feature_op_dict[rgb_clear_view[0]]
            pregrasp_image_rgb_op = self._rgb_preprocessing(pregrasp_image_rgb_op,
                                                            imagenet_mean_subtraction=imagenet_mean_subtraction,
                                                            random_crop=random_crop,
                                                            resize=resize)

            grasp_success_op = tf.squeeze(fixed_feature_op_dict[grasp_success[0]])
            # each step in the grasp motion is also its own minibatch,
            # iterate in reversed direction because if training data will be dropped
            # it should be the first steps not the last steps.
            for i, (grasp_step_rgb_feature_name, pose_op_param) in enumerate(zip(reversed(rgb_move_to_grasp_steps), reversed(pose_op_params))):
                if grasp_sequence_max_time_steps is None or i < grasp_sequence_max_time_steps:
                    if int(grasp_step_rgb_feature_name.split('/')[1]) != int(pose_op_param.split('/')[1]):
                        raise ValueError('ERROR: the time step of the grasp step does not match the motion command params, '
                                         'make sure the lists are indexed correctly!')
                    pregrasp_op_batch.append(pregrasp_image_rgb_op)
                    grasp_step_rgb_feature_op = self._rgb_preprocessing(fixed_feature_op_dict[grasp_step_rgb_feature_name])
                    grasp_step_op_batch.append(grasp_step_rgb_feature_op)
                    print("fixed_feature_op_dict[pose_op_param]: ", fixed_feature_op_dict[pose_op_param])
                    simplified_grasp_command_op_batch.append(fixed_feature_op_dict[pose_op_param])
                    grasp_success_op_batch.append(grasp_success_op)

        # TODO(ahundt) for multiple device batches, will need to split on batch_size and example_batch size will need to be updated
        example_batch_size = len(grasp_success_op_batch)

        pregrasp_op_batch = tf.parallel_stack(pregrasp_op_batch)
        grasp_step_op_batch = tf.parallel_stack(grasp_step_op_batch)
        simplified_grasp_command_op_batch = tf.parallel_stack(simplified_grasp_command_op_batch)
        grasp_success_op_batch = tf.parallel_stack(grasp_success_op_batch)

        pregrasp_op_batch = tf.concat(pregrasp_op_batch, 0)
        grasp_step_op_batch = tf.concat(grasp_step_op_batch, 0)
        simplified_grasp_command_op_batch = tf.concat(simplified_grasp_command_op_batch, 0)
        grasp_success_op_batch = tf.concat(grasp_success_op_batch, 0)
        # add one extra dimension so they match
        grasp_success_op_batch = tf.expand_dims(grasp_success_op_batch, -1)

        if resize:
            input_image_shape = [resize_height, resize_width, 3]
        else:
            input_image_shape = [512, 640, 3]

        ########################################################
        # End tensor configuration, begin model configuration and training

        weights_name = timeStamped(save_weights)

        lr_reducer = ReduceLROnPlateau(monitor='loss', factor=np.sqrt(0.1), cooldown=0, patience=5, min_lr=0.5e-6)
        early_stopper = EarlyStopping(monitor='acc', min_delta=0.001, patience=10)
        csv_logger = CSVLogger(weights_name + '.csv')
        checkpoint = keras.callbacks.ModelCheckpoint(save_weights + '.epoch-{epoch:03d}-loss-{loss:.2f}-acc-{acc:.2f}.h5',
                                                     save_best_only=True, verbose=1, monitor='acc')

        callbacks = [lr_reducer, early_stopper, csv_logger, checkpoint]

        # 2017-08-27
        # Tried NADAM for a while with the settings below, only improved for first 2 epochs.
        # Will need to try more things later.
        # Nadam parameter choice reference:
        # https://github.com/tensorflow/tensorflow/pull/9175#issuecomment-295395355
        # optimizer = keras.optimizers.Nadam(lr=0.004, beta_1=0.825, beta_2=0.99685)

        # 2017-08-28 trying SGD
        optimizer = keras.optimizers.SGD(lr=1e-2)

        # create the model
        model = make_model_fn(
            pregrasp_op_batch,
            grasp_step_op_batch,
            simplified_grasp_command_op_batch,
            input_image_shape=input_image_shape,
            batch_size=example_batch_size)

        if(load_weights):
            if os.path.isfile(load_weights):
                model.load_weights(load_weights)
            else:
                print('Could not load weights {}, '
                      'the file does not exist, '
                      'starting fresh....'.format(load_weights))

        model.compile(optimizer=optimizer,
                      loss='binary_crossentropy',
                      metrics=['accuracy'],
                      target_tensors=[grasp_success_op_batch])

        model.summary()

        # make sure we visit every image once
        steps_per_epoch = int(np.ceil(float(num_samples)/float(batch_size)))

        try:
            model.fit(epochs=epochs, steps_per_epoch=steps_per_epoch, callbacks=callbacks)
        except KeyboardInterrupt, e:
            # save weights if the user asked to end training
            pass
        model.save_weights(weights_name + '_final.h5')


if __name__ == '__main__':

    with K.get_session() as sess:
        if FLAGS.grasp_model is 'grasp_model_single':
            model_fn = grasp_model.grasp_model
        elif FLAGS.grasp_model is 'grasp_model_segmentation':
            model_fn = grasp_model.grasp_model_segmentation
        else:
            raise ValueError('unknown model selected: {}'.format(FLAGS.grasp_model))

        gt = GraspTrain()
        gt.train(make_model_fn=model_fn)
