"""
Targeting logic
"""

import random
from enum import IntEnum
from .enums import Affiliation, CardType, PlayReq, GameTag, Race, Zone
from .utils import CardList


# Requirements-based targeting
def is_valid_target(self, target, requirements=None):
	if target.type == CardType.MINION:
		if target.dead:
			return False
		if target.stealthed and self.controller != target.controller:
			return False
		if target.immune and self.controller != target.controller:
			return False
		if self.type == CardType.SPELL and target.cant_be_targeted_by_abilities:
			return False
		if self.type == CardType.HERO_POWER and target.cant_be_targeted_by_hero_powers:
			return False

	if requirements is None:
		requirements = self.requirements

	for req, param in requirements.items():
		if req == PlayReq.REQ_MINION_TARGET:
			if target.type != CardType.MINION:
				return False
		elif req == PlayReq.REQ_FRIENDLY_TARGET:
			if target.controller != self.controller:
				return False
		elif req == PlayReq.REQ_ENEMY_TARGET:
			if target.controller == self.controller:
				return False
		elif req == PlayReq.REQ_DAMAGED_TARGET:
			if not target.damage:
				return False
		elif req == PlayReq.REQ_YOUR_TURN:
			if not self.controller.current_player:
				return False
		elif req == PlayReq.REQ_TARGET_MAX_ATTACK:
			if target.atk > param or 0:
				return False
		elif req == PlayReq.REQ_NONSELF_TARGET:
			if target is self:
				return False
		elif req == PlayReq.REQ_TARGET_WITH_RACE:
			if target.type != CardType.MINION or target.race != param:
				return False
		elif req == PlayReq.REQ_HERO_TARGET:
			if target.type != CardType.HERO:
				return False
		elif req == PlayReq.REQ_TARGET_MIN_ATTACK:
			if target.atk < param or 0:
				return False
		elif req == PlayReq.REQ_MUST_TARGET_TAUNTER:
			if not target.taunt:
				return False
		elif req == PlayReq.REQ_UNDAMAGED_TARGET:
			if target.damage:
				return False

		# fireplace reqs
		elif req == PlayReq.REQ_SPELL_TARGET:
			if target.type != CardType.SPELL:
				return False
		elif req == PlayReq.REQ_SECRET_TARGET:
			if target.type != CardType.SPELL or not target.secret:
				return False
		elif req == PlayReq.REQ_WEAPON_TARGET:
			if target.type != CardType.WEAPON:
				return False
		elif req == PlayReq.REQ_NO_MINIONS_PLAYED_THIS_TURN:
			if self.controller.minions_played_this_turn:
				return False
		elif req == PlayReq.REQ_TARGET_HAS_BATTLECRY:
			if not target.has_battlecry:
				return False
		elif req == PlayReq.REQ_SOURCE_IS_ENRAGED:
			if not self.enraged:
				return False
	return True


class Selector:
	"""
	A Forth-like program consisting of methods of Selector and members of
	IntEnum classes. The IntEnums must have appropriate test(entity)
	methods returning a boolean, true if entity matches the condition.
	"""
	class MergeFilter:
		"""
		Signals the start of a merge: the following commands define the filter
		to be passed after Merge
		"""
		pass

	class Merge:
		"""
		Ops between Merge and Unmerge are classes with merge(selector, entities)
		methods that operate on the full collection specified by the ops between
		MergeFilter and Merge.
		"""
		pass

	class Unmerge:
		pass

	def __init__(self, *args):
		self.program = []
		first = True
		for arg in args:
			self.program.append(arg)
			if not first:
				self.program.append(Selector._or)
			first = False

	def __repr__(self):
		prog = []
		for op in self.program:
			name = ""
			if hasattr(op, "__name__"):
				name = op.__name__
			elif isinstance(op, IntEnum):
				name = op.name
			else:
				name = repr(op)
			prog.append(name.lstrip("_"))
		return "<{}: {}>".format(self.__class__.__name__, " ".join(prog))

	def __or__(self, other):
		result = Selector()
		result.program = self.program + other.program
		result.program.append(Selector._or)
		return result

	def __add__(self, other):
		result = Selector()
		result.program = self.program + other.program
		result.program.append(Selector._and)
		return result

	def __sub__(self, other):
		result = Selector()
		result.program = self.program + other.program
		result.program += [Selector._not, Selector._and]
		return result

	def eval(self, entities, source):
		if not entities:
			return []
		self.opc = 0  # outer program counter
		result = []
		while self.opc < len(self.program):
			if self.program[self.opc] != Selector.MergeFilter:
				result += [e for e in entities if self.test(e, source)]
				self.opc = self.pc
				if self.opc >= len(self.program):
					break
			else:
				self.opc += 1
			# handle merge step:
			merge_input = CardList([e for e in entities if self.test(e, source)])
			self.opc = self.pc
			merge_output = CardList()
			while self.opc < len(self.program):
				op = self.program[self.opc]
				self.opc += 1
				if op == Selector.Unmerge:
					break
				merge_output += op.merge(self, merge_input)
			negated = False
			combined = False
			while self.opc < len(self.program):
				# special handling for operators on merged collections:
				op = self.program[self.opc]
				if op == Selector._or:
					result += [e for e in merge_output]
					combined = True
				elif op == Selector._and:
					result = [e for e in result if (e in merge_output) != negated]
					combined = True
				elif op == Selector._not:
					negated = not negated
				else:
					break
				self.opc += 1
			if not combined:
				# assume or
				result += merge_output
		return result

	def test(self, entity, source):
		stack = []
		self.pc = self.opc  # program counter
		while self.pc < len(self.program):
			op = self.program[self.pc]
			self.pc += 1
			if op == Selector.Merge or op == Selector.MergeFilter:
				break
			if callable(op):
				op(self, stack)
			else:
				val = type(op).test(op, entity, source)
				stack.append(val)
		return stack[-1]

	# boolean ops:
	def _and(self, stack):
		a = stack.pop()
		b = stack.pop()
		stack.append(a and b)

	def _or(self, stack):
		a = stack.pop()
		b = stack.pop()
		stack.append(a or b)

	def _not(self, stack):
		stack.append(not stack.pop())


class SelfSelector(Selector):
	"""
	Selects the source.
	"""
	class IsSelf:
		def test(self, entity, source):
			return entity is source

	def __init__(self):
		self.program = [self.IsSelf()]

	def eval(self, entities, source):
		return [source]

	def test(self, entity, source):
		return entity is source

SELF = SelfSelector()


class OwnerSelector(Selector):
	"""
	Selects the source's owner.
	"""
	class IsOwner:
		def test(self, entity, source):
			return entity is source.owner

	def __init__(self):
		self.program = [self.IsOwner()]

	def eval(self, entities, source):
		if source.owner:
			return [source.owner]
		return []

	def test(self, entity, source):
		return entity is source.owner

OWNER = OwnerSelector()


class TargetSelector(Selector):
	"""
	Selects the source's target as target.
	"""
	class IsTarget:
		def test(self, entity, source):
			return entity is source.target

	def __init__(self):
		self.program = [self.IsTarget()]

	def eval(self, entities, source):
		return [source.target]

	def test(self, entity, source):
		return entity is source.target

TARGET = TargetSelector()


class AdjacentSelector(Selector):
	"""
	Selects the minions adjacent to the targets.
	"""
	class SelectAdjacent:
		def merge(self, selector, entities):
			result = []
			for e in entities:
				result.extend(e.adjacent_minions)
			return result

	def __init__(self, selector):
		self.program = [Selector.MergeFilter]
		self.program.extend(selector.program)
		self.program.append(Selector.Merge)
		self.program.append(self.SelectAdjacent())
		self.program.append(Selector.Unmerge)

SELF_ADJACENT = AdjacentSelector(SELF)
TARGET_ADJACENT = AdjacentSelector(TARGET)


class RandomSelector(Selector):
	"""
	Selects a 1-member random sample of the targets.
	This selector can be multiplied to select more than 1 target.
	"""
	class SelectRandom:
		def __init__(self, times):
			self.times = times

		def merge(self, selector, entities):
			if not entities and self.fallback:
				return [self.fallback]
			return random.sample(entities, min(len(entities), self.times))

	def __init__(self, selector):
		self.random = self.SelectRandom(1)
		self.random.fallback = None
		self.selector = selector
		self.program = [Selector.MergeFilter]
		self.program.extend(selector.program)
		self.program.append(Selector.Merge)
		self.program.append(self.random)
		self.program.append(Selector.Unmerge)

	def __mul__(self, other):
		result = RandomSelector(self.selector)
		result.random.times = self.random.times * other
		return result

	def __or__(self, other):
		self.random.fallback = other
		return self

RANDOM = RandomSelector


DAMAGED = Selector(GameTag.DAMAGE)
DEATHRATTLE = Selector(GameTag.DEATHRATTLE)
OVERLOAD = Selector(GameTag.RECALL)


IN_PLAY = Selector(Zone.PLAY)
IN_DECK = Selector(Zone.DECK)
IN_HAND = Selector(Zone.HAND)
HIDDEN = Selector(Zone.SECRET)

FRIENDLY = Selector(Affiliation.FRIENDLY)
ENEMY = Selector(Affiliation.HOSTILE)
CONTROLLED_BY_TARGET = Selector(Affiliation.TARGET)

ALL_PLAYERS = PLAYER = Selector(CardType.PLAYER)
CONTROLLER = PLAYER + FRIENDLY
OPPONENT = PLAYER + ENEMY
TARGET_PLAYER = ALL_PLAYERS + CONTROLLED_BY_TARGET

HERO = Selector(CardType.HERO)
MINION = Selector(CardType.MINION)
CHARACTER = MINION | HERO
WEAPON = Selector(CardType.WEAPON)
SPELL = Selector(CardType.SPELL)
SECRET = Selector(CardType.SECRET)
HERO_POWER = Selector(CardType.HERO_POWER)

BEAST = Selector(Race.BEAST)
DEMON = Selector(Race.DEMON)
MECH = Selector(Race.MECHANICAL)
MURLOC = Selector(Race.MURLOC)
PIRATE = Selector(Race.PIRATE)
TOTEM = Selector(Race.TOTEM)

CONTROLLER_HAND = IN_HAND + FRIENDLY
CONTROLLER_DECK = IN_DECK + FRIENDLY
OPPONENT_HAND = IN_HAND + ENEMY
OPPONENT_DECK = IN_DECK + ENEMY

ALL_HEROES = IN_PLAY + HERO
ALL_MINIONS = IN_PLAY + MINION
ALL_CHARACTERS = IN_PLAY + CHARACTER
ALL_WEAPONS = IN_PLAY + WEAPON
ALL_SECRETS = HIDDEN + SECRET
ALL_HERO_POWERS = IN_PLAY + HERO_POWER

FRIENDLY_HERO = IN_PLAY + FRIENDLY + HERO
FRIENDLY_MINIONS = IN_PLAY + FRIENDLY + MINION
FRIENDLY_CHARACTERS = IN_PLAY + FRIENDLY + CHARACTER
FRIENDLY_WEAPON = IN_PLAY + FRIENDLY + WEAPON
FRIENDLY_SECRETS = HIDDEN + FRIENDLY + SECRET
FRIENDLY_HERO_POWER = IN_PLAY + FRIENDLY + HERO_POWER
ENEMY_HERO = IN_PLAY + ENEMY + HERO
ENEMY_MINIONS = IN_PLAY + ENEMY + MINION
ENEMY_CHARACTERS = IN_PLAY + ENEMY + CHARACTER
ENEMY_WEAPON = IN_PLAY + ENEMY + WEAPON
ENEMY_SECRETS = HIDDEN + ENEMY + SECRET
ENEMY_HERO_POWER = IN_PLAY + ENEMY + HERO_POWER

RANDOM_MINION = RANDOM(ALL_MINIONS)
RANDOM_CHARACTER = RANDOM(ALL_CHARACTERS)
RANDOM_FRIENDLY_MINION = RANDOM(FRIENDLY_MINIONS)
RANDOM_OTHER_FRIENDLY_MINION = RANDOM(FRIENDLY_MINIONS - SELF)
RANDOM_FRIENDLY_CHARACTER = RANDOM(FRIENDLY_CHARACTERS)
RANDOM_ENEMY_MINION = RANDOM(ENEMY_MINIONS)
RANDOM_ENEMY_CHARACTER = RANDOM(ENEMY_CHARACTERS)

DAMAGED_CHARACTERS = ALL_CHARACTERS + DAMAGED
