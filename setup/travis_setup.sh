#!/usr/bin/env bash

export ROS_DISTRO=indigo
export ROS_CI_DESKTOP="`lsb_release -cs`"  # e.g. [precise|trusty|...]
export CI_SOURCE_PATH=$(pwd)
export CATKIN_OPTIONS="$CI_SOURCE_PATH/catkin.options"
export ROS_PARALLEL_JOBS='-j8 -l6'
export CATKIN_WS="$HOME/costar_ws"
export COSTAR_PLAN_DIR="$HOME/costar_ws/src/costar_plan"

sudo apt-get update -qq
sudo rm -rf /var/lib/apt/lists/*

echo "======================================================"
echo "PYTHON"
echo "Installing python dependencies:"
echo "Installing basics from apt-get..."
sudo apt-get -y install python-pygame python-dev
echo "Installing libraries and drivers..."
sudo apt-get -y install -y build-essential autoconf libtool pkg-config python-opengl python-imaging python-pyrex python-pyside.qtopengl idle-python2.7 qt4-dev-tools qt4-designer libqtgui4 libqtcore4 libqt4-xml libqt4-test libqt4-script libqt4-network libqt4-dbus python-qt4 python-qt4-gl libgle3 python-dev libssl-dev
sudo apt-get -y install -y libx11-dev libpq-dev python-dev libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev libffi-dev
echo "Installing smaller libraries from pip..."
sudo -H pip install --no-binary numpy
sudo -H pip install h5py keras keras-rl sympy matplotlib pygame gmr networkx \
  dtw pypr gym PyPNG pybullet numba

echo "======================================================"
echo "Installing major libraries"

# Set up PCL 1.7.2
sudo add-apt-repository --yes ppa:v-launchpad-jochen-sprickerhof-de/pcl 
sudo apt-get update 
sudo apt-get install -y libpcl-all ros-$ROS_DISTRO-pcl-ros
#sudo apt-get install -y libpcl-dev ros-$ROS_DISTRO-pcl-ros # for kinetic

# Set up Opencv-nonfree
sudo add-apt-repository --yes ppa:xqms/opencv-nonfree
sudo apt-get update 
sudo apt-get install -y libopencv-nonfree-dev
echo "======================================================"
echo "installing ROS"

sudo sh -c 'echo "deb http://packages.ros.org/ros/ubuntu $(lsb_release -sc) main" > /etc/apt/sources.list.d/ros-latest.list'
sudo apt-key adv --keyserver ha.pool.sks-keyservers.net --recv-keys 421C365BD9FF1F717815A3895523BAEEB01FA116

# updates
sudo apt-get update -qq

# install indigo
sudo apt-get -y install ros-$ROS_DISTRO-desktop-full

sudo rosdep init
rosdep update

echo "source /opt/ros/$ROS_DISTRO/setup.bash" >> ~/.bashrc
source $HOME/.bashrc
sudo apt-get -y install python-rosinstall


echo "======================================================"
echo "ROS"
sudo apt-get install -y python-catkin-pkg python-rosdep python-wstool \
  python-catkin-tools ros-$ROS_DISTRO-catkin ros-$ROS_DISTRO-ros-base
echo "--> source ROS setup in /opt/ros/$ROS_DISTRO/setup.bash"
source /opt/ros/$ROS_DISTRO/setup.bash
sudo rosdep init
rosdep update


echo "======================================================"
echo "CATKIN"
echo "Create catkin workspace..."
mkdir -p $CATKIN_WS/src
cd $CATKIN_WS
source /opt/ros/indigo/setup.bash
catkin init
cd $CATKIN_WS/src

git clone https://github.com/cpaxton/hrl-kdl.git  --branch indigo-devel
git clone https://github.com/cburbridge/python_pcd.git
git clone https://github.com/jhu-lcsr/costar_objects.git
git clone https://github.com/cpaxton/dmp.git --branch indigo
git clone https://github.com/cpaxton/robotiq_85_gripper.git

# Need to find less complicated way to integrate the repo besides annoying ssh authentication
# git clone https://a5a923019bfb3202ebdf3e3eb63b7866c913218d@github.com/cpaxton/costar_plan.git
# git clone https://github.com/fetchrobotics/fetch_gazebo.git
# git clone https://github.com/fetchrobotics/fetch_ros.git

rosdep install -y --from-paths ./ --ignore-src --rosdistro $ROS_DISTRO
cd $CATKIN_WS/src
catkin build
source $CATKIN_WS/devel/setup.bash
