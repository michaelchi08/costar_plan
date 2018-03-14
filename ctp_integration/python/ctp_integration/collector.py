
import matplotlib.pyplot as plt
import numpy as np
import PyKDL as kdl
import rospy 
import tf2_ros as tf2
import tf_conversions.posemath as pm

from costar_models.datasets.npz import NpzDataset
from costar_models.datasets.h5f import H5fDataset
from costar_models.datasets.image import *

from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image
from sensor_msgs.msg import JointState
from std_msgs.msg import String

class DataCollector(object):
    '''
    Manages data collection. Will consume:
    - images from camera
    - depth data (optional)
    - current end effector pose
    - current joint states
    - current gripper status
    '''
    js_topic = "joint_states"
    rgb_topic = "camera/rgb/image_raw"
    depth_topic = "camera/depth_registered/image_raw"
    ee = "endpoint"
    base_link = "base_link"
    description = "/robot_description"
    data_types = ["h5f", "npz"]
    info_topic = "/costar/info"
    object_topic = "/costar/SmartMove/object"

    def __init__(self, robot_config,
            task,
            data_type="h5f",
            rate=10,
            data_root=".",
            img_shape=(128,128),
            camera_frame = "camera_link",
            tf_listener=None):

        '''
        Set up the writer (to save trials to disk) and subscribers (to process
        input from ROS and store the current state).
        '''
        self.verbosity = 0

        if tf_listener is not None:
            self.tf_listener = tf_listener
        else:
            self.tf_listener = tf.TransformListener()

        if isinstance(rate, int) or isinstance(rate, float):
            self.rate = rospy.Rate(rate)
        elif isinstance(rate, rospy.Rate):
            self.rate = rate
        else:
            raise RuntimeError("rate data type not supported: %s" % type(rate))

        self.root = data_root
        self.data_type = data_type
        rospy.logwarn("Dataset root set to " + str(self.root))
        if self.data_type == "h5f":
            self.writer = H5fDataset(self.root)
        elif self.data_type == "npz":
            self.writer = NpzDataset(self.root)
        else:
            raise RuntimeError("data type %s not supported" % data_type)

        self.T_world_ee = None
        self.T_world_camera = None
        self.camera_frame = camera_frame
        self.ee_frame = robot_config['end_link']

        self.q = None
        self.dq = None
        self.pc = None
        self.camera_depth_info = None
        self.camera_rgb_info = None
        self.depth_img = None
        self.rgb_img = None

        #self._camera_depth_info_sub = rospy.Subscriber(camera_depth_info_topic, CameraInfo, self._depthInfoCb)
        #self._camera_rgb_info_sub = rospy.Subscriber(camera_rgb_info_topic, CameraInfo, self._rgbInfoCb)
        self._rgb_sub = rospy.Subscriber(self.rgb_topic, Image, self._rgbCb)
        self._depth_sub = rospy.Subscriber(self.depth_topic, Image, self._depthCb)
        self._joints_sub = rospy.Subscriber(self.js_topic,
                JointState,
                self._jointsCb)
        self._info_sub = rospy.Subscriber(self.info_topic,
                String, 
                self._infoCb)
        self._smartmove_object_sub = rospy.Subscriber(self.object_topic,
                String,
                self._objectCb)

        self._bridge = CvBridge()
 
        self.task = task
        self.reset()

        self.verbosity = 1

    def _rgbCb(self, msg):
        try:
            cv_image = self._bridge.imgmsg_to_cv2(msg, "rgb8")
            self.rgb_img = np.asarray(cv_image)
            #print(self.rgb_img)
        except CvBridgeError as e:
            rospy.logwarn(str(e))

    def _infoCb(self, msg):
        self.info = msg.data

    def _objectCb(self, msg):
        self.object = msg.data

    def _depthCb(self, msg):
        try:
            cv_image = self._bridge.imgmsg_to_cv2(msg)
            self.depth_img = np.asarray(cv_image)
            #print (self.depth_img)
        except CvBridgeError as e:
            rospy.logwarn(str(e))

    def setTask(self, task):
        self.task = task

    def reset(self):
        self.data = {}
        self.data["q"] = []
        self.data["dq"] = []
        self.data["pose"] = []
        self.data["camera"] = []
        self.data["image"] = []
        self.data["label"] = []
        self.data["info"] = []
        self.data["object"] = []
        self.data["object_pose"] = []
        self.data["labels_to_name"] = list(self.task.labels)
        #self.data["depth"] = []

        self.info = None
        self.object = None
        self.current = None

    def _jointsCb(self, msg):
        self.q = msg.position
        self.dq = msg.velocity
        if self.verbosity > 3:
            rospy.loginfo(self.q, self.dq)

    def save(self, seed, result):
        '''
        Save function that wraps data set access.
        '''
        for k, v in self.data.items():
            print(k, np.array(v).shape)
        print(self.data["label"])

        # for now all examples are considered a success
        self.writer.write(self.data, seed, result)
        self.reset()

    def update(self, action_label, ):
        '''
        Compute endpoint positions and update data. Should happen at some
        fixed frequency like 10 hz.

        Parameters:
        -----------
        action: name of high level action being executed
        '''

        if not self.current == action_label:
            rospy.loginfo("new action: " + str(action_label))
            self.current = action_label
            self.object = None
        if self.object is None:
            rospy.logwarn("passing -- has not yet started executing motion")
            return True

        try:
            t = rospy.Time(0)
            c_pose = self.tf_listener.lookup_transform(self.base_link, self.camera_frame, t)
            ee_pose = self.tf_listener.lookup_transform(self.base_link, self.ee_frame, t)
            obj_pose = self.tf_listener.lookup_transform(self.base_link, self.object, t)
        except (tf2.LookupException, tf2.ExtrapolationException, tf2.ConnectivityException) as e:
            rospy.logwarn("Failed lookup: %s to %s, %s"%(self.base_link, self.camera_frame, self.ee_frame))
            return False

        print(self.info, self.object)

        c_xyz = [c_pose.transform.translation.x,
                 c_pose.transform.translation.y,
                 c_pose.transform.translation.z,]
        c_quat = [c_pose.transform.rotation.x,
                  c_pose.transform.rotation.y,
                  c_pose.transform.rotation.z,
                  c_pose.transform.rotation.w,]
        ee_xyz = [ee_pose.transform.translation.x,
                 ee_pose.transform.translation.y,
                 ee_pose.transform.translation.z,]
        ee_quat = [ee_pose.transform.rotation.x,
                  ee_pose.transform.rotation.y,
                  ee_pose.transform.rotation.z,
                  ee_pose.transform.rotation.w,]
        obj_xyz = [obj_pose.transform.translation.x,
                 obj_pose.transform.translation.y,
                 obj_pose.transform.translation.z,]
        obj_quat = [obj_pose.transform.rotation.x,
                  obj_pose.transform.rotation.y,
                  obj_pose.transform.rotation.z,
                  obj_pose.transform.rotation.w,]

        self.data["q"].append(np.copy(self.q)) # joint position
        self.data["dq"].append(np.copy(self.dq)) # joint velocuity
        self.data["pose"].append(ee_xyz + ee_quat) # end effector pose (6 DOF)
        self.data["camera"].append(c_xyz + c_quat) # camera pose (6 DOF)
        #plt.figure()
        #plt.imshow(self.rgb_img)
        #plt.show()
        self.data["image"].append(GetJpeg(self.rgb_img)) # encoded as JPEG

        # TODO(cpaxton): 
        if not action_label in self.labels:
            raise RuntimeError("action not recognized: " + str(action_label))

        action = self.task.index(action_label)
        self.data["label"].append(action) # integer code for high-level action
        self.data["info"].append(self.info) # string description of current step
        self.data["object"].append(self.object)

        # TODO(cpaxton): add pose of manipulated object
        self.data["object_pose"].append(obj_xyz + obj_quat)
        #self.data["depth"].append(GetJpeg(self.depth_img))

        return True

if __name__ == '__main__':
    pass


