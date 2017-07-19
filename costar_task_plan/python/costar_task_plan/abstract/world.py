import copy

from state import AbstractState
from action import AbstractAction

class AbstractWorld(object):
  '''
  Nonspecific implementation that encapsulates a particular RL/planning problem.
  It contains actors, condition, and a reward function.
  In particular, it points to one actor called the LEARNER, who we care about.
  '''

  # This is fixed: it's the actor that is doing learning and planning in the
  # world.
  learner = 0

  # ID of the current trace; should be completely unique
  next_trace_id = 0

  def __init__(self, reward, verbose=False):
    self.reward = reward
    self.verbose = verbose
    self.actors = []
    self.conditions = []
    self.features = None
    self.initial_features = None
    self.initial_reward = 0
    self.done = False
    self.predicates = []
    self.predicate_idx = {}
    self.num_actors = 0
    self.task = None
    self.dt = 0.1
    self.ticks = 0
    self.max_ticks = 100
    self.scale_reward_to_max_ticks = False

  def vectorize(self, control, features, reward, done, example, action_label):
    '''
    Convert current observations to a vector of data.
    '''
    desc = self.features.description
    if isinstance(features, tuple):
        assert len(desc) ==  len(features)
        data = zip(self.features.description, features)
    else:
        assert not isinstance(desc, tuple)
        data = [(desc, features)]
    actor = self.actors[0]
    params = actor.state.toParams(control)
    if isinstance(params, tuple):
        for desc, param in zip(control.getDescription(), params):
            data.append((desc, param))
    else:
        data.append(control.getDescription(), params)
    data += [("reward", reward),
             ("done", done),
             ("example", example),
             ("label", action_label)]
    return data

  def time(self):
      return self.dt * self.ticks

  def updateTraceID(self):
    self.trace_id = self.next_trace_id
    self.next_trace_id += 1

  def zeroAction(self, actor_id=0):
    raise NotImplementedError('This should be overridden by the child class '
        'implementing the world.')

  def setTask(self, task):
    self.task = task

  def addActor(self, actor):
    actor_id = len(self.actors)
    actor.setId(actor_id)
    actor.state.updatePredicates(self, actor)
    self.actors.append(actor)
    self.num_actors = len(self.actors)
    return actor_id

  def addCondition(self, condition, weight, name):
    self.conditions.append((condition, weight, name))

  # override this if there's some cleanup logic that needs to happen after dynamics updates
  def hook(self):
    raise NotImplementedError('This should be overridden by the child class '
        'implementing the world. It implements the world global update rules, '
        'and ensures the world is in a valid state after all actors collect '
        'independent updates.')

  def getFeatureBounds(self):
    return self.features.getBounds()

  def setFeatures(self, features):
    features.updateBounds(self)
    self.features = features

  def addPredicate(self, predicate, predicate_check):
    idx = len(self.predicates)
    self.predicate_idx[predicate] = idx
    predicate_check.setIndex(idx)
    self.predicates.append((predicate, predicate_check))

  def fork(self, action, policies={}):
    '''
    Create an exact copy of the world at its current state. This is useful for
    advancing world state for optimization and things like that without using
    an OpenAI gym environment.

    For use in planning:
    - take an action
    - take an optional set of policies

    Create a copy of the world and tick() with the appropriate new action. If
    we have policies, actors will be reset appropriately to use new policies.
    '''
    new_world = copy.copy(self)
    # NOTE: this is where the inefficiency lies.
    #new_world.actors = copy.deepcopy(self.actors)
    new_world.actors = [copy.copy(actor) for actor in self.actors]
    new_world.updateTraceID()

    # If the action is not valid, take a zero action and update the world
    # appropriately.
    if action is None:
      action = self.zeroAction(0)

    (res, S0, A0, S1, F1, r) = new_world.tick(action)
    return new_world

  def duplicate(self):
    '''
    '''
    new_world = copy.copy(self)
    new_world.actors = [copy.copy(actor) for actor in self.actors]
    new_world.updateTraceID()

  def tick(self, A0):
    '''
    Main update loop for the World class. 
    This resolves all the logic in the world by updating each actor according
    to its last observation of the world state. It also calls the hook()
    function to complete application-specific world update logic.
    '''
    self.ticks += 1

    S0 = self.actors[0].state

    # track list of actions for all entities
    actions = [0]*len(self.actors)
    for i, actor in enumerate(self.actors):
      if i is 0:
        actions[i] = A0
      else:
        actions[i] = actor.evaluate(self)

    # update all actors in a separate loop
    for actor, action in zip(self.actors, actions):
      s = actor.update(action, self.dt)

    self.hook() # run update hook for this environment

    S1 = self.actors[0].state

    # set up vectors of predicates properly
    for actor in self.actors:
        actor.state.predicates = [0] * len(self.predicates)
   
    # update all actors
    #self.predicates = [check(world, self, actor, actor.last_state)
    #for actor in self.actors:
    #  actor.state.updatePredicates(self, actor)
    for i, (name, check) in enumerate(self.predicates):
      for actor in self.actors:
        actor.state.predicates[i] = check(
            self,
            actor.state,
            actor,
            actor.last_state)

    (res, F1, r, rt) = self._process() # get the final set of variables

    if not res and self.scale_reward_to_max_ticks:
        # compute difference here
        d_ticks = max(0, self.max_ticks - self.ticks)
        r *= 1 + d_ticks

    # update features and reward
    self.initial_features = F1
    self.initial_reward = r + rt
    self.done = not res

    return (res, S0, A0, S1, F1, r + rt)

  def _process(self):
    # compute features
    if self.features is not None:
      # NOTE: this is about 0.1 second right now in larger trees
      F1 = self.computeFeatures()
    else:
      F1 = None
    r, bonus = self.reward(self)
    rt = bonus

    # determine if we should terminate
    res = True
    actor = self.actors[0]
    state = actor.state
    prev_state = actor.last_state
    for (condition, weight, name) in self.conditions:
      if not condition(self, state, actor, prev_state):
        if self.verbose:
          print "Constraint violated: %s, score modifier: %f"%(name,weight)
        res = False
        rt = rt + weight

    return res, F1, r, rt

  def computeFeatures(self):
    '''
    May be overridden in some cases
    '''
    return self.features(self, self.actors[0].state)

  def updateFeatures(self):
    self.initial_features = self.computeFeatures()

  def reset(self):
    '''
    Destroy all current actors.
    '''
    self.actors = []
    self.done = False
    self.ticks = 0
    self._reset()

  def setSprites(self, sprites):
    '''
    Specify graphics to use when drawing this world. Not used for the various
    robotics-based tasks at all.
    TODO(cpaxton): refactor this and put it in the right subclass of World.
    '''
    self.sprites = sprites
    self.draw_sprites = len(sprites) > 0

  def clearSprites(self):
    '''
    Clear any graphics used to draw this world. Again, this is not used for the
    various robotics tasks.
    TODO(cpaxton): refactor this and put it in the right subclass of World.
    '''
    self.sprites = []
    self.draw_sprites = False

  def getObjects(self):
    '''
    Return information about specific objects in the world. This should tell us
    for some semantic identifier which entities in the world correspond to that.
    As an example:
        {
            "goal": ["goal1", "goal2"]
        }
    Would be a reasonable response, saying that there are two goals called
    goal1 and goal2.
    '''
    return {}

  def debugPredicates(self, state):
    '''
    Just prints out a bunch of predicate information for all the current set of
    predicates on a particular state.
    '''
    for p, (n, c) in zip(state.predicates, self.predicates):
      print n,"=",p,","
    print ""

  def getLearner(self):
    '''
    This is the "player" whose moves we want to optimize.
    '''
    return self.actors[0]

  def _createObjectActor(self, *args):
      '''
      This function is a helper that should return an individual ACTOR. This actor
      stores information pertaining to a particular entity in the world that has
      an associated state and must be checked by the world on each iteration.

      In general, some actors will have an associated policy and will take actions;
      actors added via this function should not do so.
      '''
      raise NotImplementedError('if your world wants to support adding '
                                'objects, then you must implement the '
                                '_createObjectActor function.')
