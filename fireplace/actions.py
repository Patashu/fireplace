import logging
import random
from itertools import chain
from .enums import CardType, PowSubType, Zone
from .entity import Entity, new_order_of_play


class RandomCardGenerator(object):
	"""
	Store filters and generate a random card matching the filters on pick()
	"""
	def __init__(self, **filters):
		self.filters = filters
		self._cards = None

	@property
	def cards(self):
		if self._cards is None:
			from . import cards
			self._cards = cards.filter(**self.filters)
		return self._cards

	def pick(self) -> str:
		return random.choice(self.cards)


class Evaluator:
	"""
	Lazily evaluate a condition at runtime.
	"""
	def __init__(self):
		self._if = None
		self._else = None

	def __and__(self, action):
		self._if = action
		return self

	def __or__(self, action):
		self._else = action
		return self

	def get_actions(self, source, game):
		ret = self.evaluate(source, game)
		if ret:
			if self._if:
				if isinstance(self._if, Action):
					return [self._if]
				return self._if
		elif self._else:
			if isinstance(self._else, Action):
				return [self._else]
			return [self._else]
		return []

	def trigger(self, source, game):
		for action in self.get_actions(source, game):
			action.trigger(source, game)


class Dead(Evaluator):
	"""
	Evaluates to True if every target in \a selector is dead
	"""
	def __init__(self, selector):
		super().__init__()
		self.selector = selector

	def evaluate(self, source, game):
		for target in self.selector.eval(game, source):
			if not target.dead:
				return False
		return True


class Find(Evaluator):
	"""
	Evaluates to True if \a selector has a match.
	"""
	def __init__(self, selector, count=1):
		super().__init__()
		self.selector = selector
		self.count = count

	def evaluate(self, source, game):
		return len(self.selector.eval(game, source)) >= self.count


class Copy(object):
	"""
	Lazily return a list of copies of the target
	"""
	def __init__(self, selector):
		self.selector = selector

	def __repr__(self):
		return "%s(%r)" % (self.__class__.__name__, self.selector)

	def pick(self, source, game) -> [str]:
		return self.selector.eval(game, source)


def _eval_card(source, game, card):
	"""
	Return a Card instance from \a card
	The card argument can be:
	- A Card instance (nothing is done)
	- The string ID of the card (the card is created)
	- A RandomCardGenerator instance (a random card is picked)
	- A Copy instance (a selector is evaluated and copies its results)
	"""

	if isinstance(card, RandomCardGenerator):
		card = card.pick()
	elif isinstance(card, Copy):
		c = card.pick(source, game)
		card = [entity.id if not isinstance(entity, str) else entity for entity in c]

	if not isinstance(card, list):
		cards = [card]
	else:
		cards = card

	ret = []
	for card in cards:
		if isinstance(card, str):
			ret.append(game.card(card))
		else:
			ret.append(card)

	return ret


class EventListener:
	ON = 1
	AFTER = 2

	def __init__(self, trigger, actions, at, zone=Zone.PLAY, once=False):
		self.trigger = trigger
		self.actions = actions
		self.at = at
		self.once = once
		self.zone = zone

	def __repr__(self):
		return "<EventListener %r>" % (self.trigger)


class Action:  # Lawsuit
	args = ()
	type = PowSubType.TRIGGER

	def __init__(self, *args, **kwargs):
		self.order_of_play = new_order_of_play()
		self.times = 1
		self._args = args
		for k, v in zip(self.args, args):
			setattr(self, k, v)

	def __repr__(self):
		args = ["%s=%r" % (k, v) for k, v in zip(self.args, self._args)]
		return "<Action: %s(%s)>" % (self.__class__.__name__, ", ".join(args))

	def __mul__(self, value):
		self.times *= value
		return self

	def after(self, *actions, zone=Zone.PLAY):
		return EventListener(self, actions, EventListener.AFTER, zone=zone)

	def on(self, *actions, zone=Zone.PLAY):
		return EventListener(self, actions, EventListener.ON, zone=zone)

	def once(self, *actions, zone=Zone.PLAY):
		return EventListener(self, actions, EventListener.ON, zone=zone, once=True)

	def broadcast(self, game, at, *args):
		for entity in chain(game.hands, game.entities):
			if entity.ignore_events:
				continue
			for event in entity._events:
				if event.zone != entity.zone:
					continue
				if isinstance(event.trigger, self.__class__) and event.at == at and event.trigger.matches(entity, args):
					actions = []
					for action in event.actions:
						if callable(action):
							actions += action(entity, *args)
						else:
							actions.append(action)
					game.queue_actions(entity, actions)
					if event.once:
						entity._events.remove(event)

	def gather(self, game, at, *args):
		result = []
		for entity in chain(game.hands, game.entities):
			if entity.ignore_events:
				continue
			for event in entity._events:
				if event.zone != entity.zone:
					continue
				if isinstance(event.trigger, self.__class__) and event.at == at and event.trigger.matches(entity, args):
					for action in event.actions:
						if callable(action):
							result += (entity, action(entity, *args))
						else:
							result.append((entity, action))
					if event.once:
						entity._events.remove(event)
		result.sort(key = x[1].order_of_play) #TODO: Figure out the best place to put sorts like these
		return result

	def matches(self, source, args):
		for arg, match in zip(args, self._args):
			# this stuff is stupidslow
			res = match.eval([arg], source)
			if not res or res[0] is not arg:
				return False
		return True


class GameAction(Action):
	def __init__(self, *args, **kwargs):
		self._args = args
		for k, v in zip(self.args, args):
			setattr(self, k, v)

	def get_args(self, source, game):
		return self._args

	def trigger(self, source, game):
		args = self.get_args(source, game)
		game.manager.action(self.type, source, *args)
		self.do(source, game, *args)
		game.manager.action_end(self.type, source, *args)
		game.process_deaths()


class Attack(GameAction):
	"""
	Make the source attack \a target
	"""
	args = ("source", "target")
	type = PowSubType.ATTACK

	def get_args(self, source, game):
		ret = super().get_args(source, game)
		self.source.attacking = True
		self.target.defending = True
		return ret

	def do(self, source, game, *args):
		game.proposed_attacker = self.source
		game.proposed_defender = self.target
		logging.info("%r attacks %r", self.source, self.target)
		self.broadcast(game, EventListener.ON, *args)
		game._attack()


class BeginTurn(GameAction):
	"""
	Make \a player begin the turn
	"""
	args = ("player", )
	type = None

	def do(self, source, game, *args):
		self.broadcast(game, EventListener.ON, self.player)
		game._begin_turn(self.player)


class Deaths(GameAction):
	"""
	Process all deaths in the PLAY Zone.
	"""

	def do(self, source, game, *args):
		game.process_deaths()


class Death(GameAction):
	"""
	Move target to the GRAVEYARD Zone.
	"""

	def do(self, source, game, target):
		self.broadcast(game, EventListener.ON, target)
		consequences_of_death = self.gather(game, EventListener.ON, target)
		if target.deathrattles:
			consequences_of_death.extend(Deathrattle(target).gather(target))
			#game.queue_actions(source, [Deathrattle(target)])
		consequences_of_death.sort(key = x[1].order_of_play)
		for entity, action in consequences_of_death:
			game.queue_actions(entity, action)


class EndTurn(GameAction):
	"""
	End the current turn
	"""
	args = ("player", )
	type = None

	def do(self, source, game, *args):
		self.broadcast(game, EventListener.ON, self.player)
		game._end_turn()


class Play(GameAction):
	"""
	Make the source player play \a card, on \a target or None.
	Choose play action from \a choose or None.
	"""
	args = ("card", "target", "choose")
	type = PowSubType.PLAY

	def get_args(self, source, game):
		return (source, ) + self._args

	def do(self, source, game, *args):
		card = self.card
		if card.has_target():
			assert self.target
		card.target = self.target

		if self.choose:
			# Choose One cards replace the action on the played card
			assert self.choose in card.data.choose_cards
			chosen = game.card(self.choose)
			chosen.controller = source
			logging.info("Choose One from %r: %r", card, chosen)
			if chosen.has_target():
				chosen.target = self.target
			card.chosen = chosen
		card.choose = self.choose

		self.broadcast(game, EventListener.ON, *args)
		game.process_deaths()
		game.play(card)
		game.process_deaths()
		self.broadcast(game, EventListener.AFTER, *args)

		card.target = None
		card.choose = None


class TargetedAction(Action):
	args = ("targets", )
	selectors = ("targets", )

	def __repr__(self):
		args = ["%s=%r" % (k, v) for k, v in zip(self.args[1:], self._args[1:])]
		return "<TargetedAction: %s(%s)>" % (self.__class__.__name__, ", ".join(args))

	def eval(self, selector, source, game):
		if isinstance(selector, Entity):
			return [selector]
		else:
			return selector.eval(game, source)

	def get_args(self, source, game, target):
		return (target, )

	def evaluate_selectors(self, source, game):
		ret = []
		for k, v in zip(self.args, self._args):
			if k in self.selectors:
				if isinstance(v, Entity):
					ret.append([v])
				elif isinstance(v, Action):
					# eg. Unstable Portal: Buff(Give(...), ...)
					ret.append(v.trigger(source, game)[0])
				else:
					ret.append(v.eval(game, source))
			else:
				ret.append(v)
		return ret

	def trigger(self, source, game):
		ret = []
		for i in range(self.times):
			args = self.evaluate_selectors(source, game)
			targets = args[0]
			game.manager.action(self.type, source, targets, *self._args)
			logging.info("%r triggering %r targeting %r", source, self, targets)
			for target in targets:
				extra_args = self.get_args(source, game, target)
				ret.append(self.do(source, game, *extra_args))
			game.manager.action_end(self.type, source, targets, *self._args)
		return ret


class Buff(TargetedAction):
	"""
	Buff character targets with Enchantment \a id
	"""
	args = ("targets", "id")

	def do(self, source, game, target):
		source.buff(target, self.id)


class Bounce(TargetedAction):
	"""
	Bounce minion targets on the field back into the hand.
	"""
	def do(self, source, game, target):
		target.bounce()


class Damage(TargetedAction):
	"""
	Damage target by \a amount.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target, *args):
		amount = target._hit(source, self.amount)
		if amount:
			self.broadcast(game, EventListener.ON, target, amount, source)


class Deathrattle(TargetedAction):
	"""
	Trigger deathrattles on card targets.
	"""
	def do(self, source, game, target):
		for deathrattle in target.deathrattles:
			if callable(deathrattle):
				actions = deathrattle(target)
			else:
				actions = deathrattle
			game.queue_actions(target, actions)

			if target.controller.extra_deathrattles:
				logging.info("Triggering deathrattles for %r again", target)
				game.queue_actions(target, actions)
	
	def gather(self, target):
		#TODO: This certainly isn't the best way to structure it, but I'll figure that out later.
		result = []
		for deathrattle in target.deathrattles:
			if callable(deathrattle):
				result.extend((target, deathrattle(target)))
			else:
				result.extend((target, deathrattle))
				
			if target.controller.extra_deathrattles: #TODO: writing it again is dumb
				logging.info("Triggering deathrattles for %r again", target)
				if callable(deathrattle):
					result.extend((target, deathrattle(target)))
				else:
					result.extend((target, deathrattle))
		result.sort(key = x[1].order_of_play) #TODO: Figure out the best place to put sorts like these
		return result

class Destroy(TargetedAction):
	"""
	Destroy character targets.
	"""
	def do(self, source, game, target):
		target._destroy()


class Discard(TargetedAction):
	"""
	Discard card targets in a player's hand
	"""
	def do(self, source, game, target):
		target.discard()


class Draw(TargetedAction):
	"""
	Make player targets draw \a count cards.
	"""
	def do(self, source, game, target):
		if not target.deck:
			target.fatigue()
			return []
		card = target.deck[-1]
		card.draw()

		return [card]


class ForceDraw(TargetedAction):
	"""
	Make player targets draw \a cards from their deck.
	"""
	args = ("targets", "cards")

	def do(self, source, game, target):
		cards = self.eval(self.cards, source, game)
		for card in cards:
			card.draw()


class ForcePlay(TargetedAction):
	"""
	Make player targets play \a cards from their hand (at no cost).
	"""
	args = ("targets", "cards")

	def do(self, source, game, target):
		cards = self.eval(self.cards, source, game)
		for card in cards:
			target.summon(card)


class FullHeal(TargetedAction):
	"""
	Fully heal character targets.
	"""
	def do(self, source, game, target):
		source.heal(target, target.health)


class GainArmor(TargetedAction):
	"""
	Make hero targets gain \a amount armor.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target):
		target.armor += self.amount
		self.broadcast(game, EventListener.ON, target, self.amount)


class GainMana(TargetedAction):
	"""
	Give player targets \a Mana crystals.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target):
		target.max_mana += self.amount


class Give(TargetedAction):
	"""
	Give player targets card \a id.
	"""
	args = ("targets", "card")

	def get_args(self, source, game, target):
		cards = _eval_card(source, game, self.card)
		return (target, cards)

	def do(self, source, game, target, cards):
		logging.debug("Giving %r to %s", cards, target)
		for card in cards:
			card.controller = target
			card.zone = Zone.HAND
		return cards


class Hit(TargetedAction):
	"""
	Hit character targets by \a amount.
	"""
	args = ("targets", "amount", "source")

	def get_args(self, source, game, target):
		if getattr(self, "source", None):
			source = self.source
		amount = self.amount
		return (target, amount, source)

	def do(self, source, game, target, amount, attack_source):
		if target.type == CardType.WEAPON:
			target.durability -= self.amount
		else:
			attack_source.hit(target, self.amount)


class Heal(TargetedAction):
	"""
	Heal character targets by \a amount.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target):
		if source.controller.outgoing_healing_adjustment:
			# "healing as damage" (hack-ish)
			return source.hit(target, self.amount)

		amount = self.amount * (source.controller.healing_double + 1)
		amount = min(amount, target.damage)
		if amount:
			# Undamaged targets do not receive heals
			logging.info("%r heals %r for %i", source, target, amount)
			target.damage -= amount
			self.broadcast(game, EventListener.ON, target, amount)


class ManaThisTurn(TargetedAction):
	"""
	Give player targets \a amount Mana this turn.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target):
		target.temp_mana += self.amount


class Mill(TargetedAction):
	"""
	Mill \a count cards from the top of the player targets' deck.
	"""
	args = ("targets", "count")

	def do(self, source, game, target):
		target.mill(self.count)


class Morph(TargetedAction):
	"""
	Morph minion target into \a minion id
	"""
	args = ("targets", "id")

	def do(self, source, game, target):
		target.morph(self.id)


class Freeze(TargetedAction):
	"""
	Freeze character targets.
	"""
	def do(self, source, game, target):
		target.frozen = True


class FillMana(TargetedAction):
	"""
	Refill \a amount mana crystals from player targets.
	"""
	args = ("targets", "amount")

	def do(self, source, game, target):
		target.used_mana -= self.amount


class Reveal(TargetedAction):
	"""
	Reveal secret targets.
	"""
	def do(self, source, game, target):
		logging.info("Revealing secret %r", target)
		self.broadcast(game, EventListener.ON, target)
		target.destroy()


class SetTag(TargetedAction):
	"""
	Sets various targets' tags to \a values.
	"""
	args = ("targets", "values")

	def do(self, source, game, target):
		for k, v in self.values.items():
			if target.tags[k] != v:
				target.tags[k] = v


class Silence(TargetedAction):
	"""
	Silence minion targets.
	"""
	def do(self, source, game, target):
		target.silence()


class Summon(TargetedAction):
	"""
	Make player targets summon \a id onto their field.
	This works for equipping weapons as well as summoning minions.
	"""
	args = ("targets", "card")

	def get_args(self, source, game, target):
		cards = _eval_card(source, game, self.card)
		return (target, cards)

	def do(self, source, game, target, cards):
		logging.info("%s summons %r", target, cards)
		if not isinstance(cards, list):
			cards = [cards]

		for card in cards:
			if card.controller != target:
				card.controller = target
			self.broadcast(game, EventListener.ON, target, card)
			card.summon()
			self.broadcast(game, EventListener.AFTER, target, card)


class Shuffle(TargetedAction):
	"""
	Shuffle card targets into player target's deck.
	"""
	args = ("targets", "card")

	def get_args(self, source, game, target):
		cards = _eval_card(source, game, self.card)
		return (target, cards)

	def do(self, source, game, target, cards):
		logging.info("%r shuffles into %s's deck", cards, target)
		if not isinstance(cards, list):
			cards = [cards]

		for card in cards:
			if card.controller != target:
				card.controller = target
			card.zone = Zone.DECK
			target.shuffle_deck()


class Swap(TargetedAction):
	"""
	Swap minion target with \a other.
	Behaviour is undefined when swapping more than two minions.
	"""
	args = ("targets", "other")

	def do(self, source, game, target):
		other = self.eval(self.other, source, game)
		if other:
			assert len(other) == 1
			other = other[0]
			orig = target.zone
			target.zone = other.zone
			other.zone = orig


class TakeControl(TargetedAction):
	"""
	Make the controller take control of targets.
	The controller is the controller of the source of the action.
	"""
	def do(self, source, game, target):
		source.controller.take_control(target)
