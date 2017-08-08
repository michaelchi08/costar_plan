from abstract import AbstractTaskDefinition
from blocks import BlocksTaskDefinition
from drl_blocks import DRLBlocksTaskDefinition
from clutter import ClutterTaskDefinition
from sorting import SortingTaskDefinition
from oranges import OrangesTaskDefinition
from obstacles import ObstaclesTaskDefinition

# TODO(cpaxton): re-enable these
# from mug import MugTaskDefinition
# from rings import RingsTaskDefinition

__all__ = ["AbstractTaskDefinition",
           "BlocksTaskDefinition",
           "DRLBlocksTaskDefinition",
           "ClutterTaskDefinition",
           "SortingTaskDefinition",
           "OrangesTaskDefinition",
           "ObstaclesTaskDefinition",
           #"RingsTaskDefinition",
           #"MugTaskDefinition",
           ]
