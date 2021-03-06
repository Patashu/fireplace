"""
Spare Parts
"""

from ..utils import *


# Armor Plating
class PART_001:
	action = [Buff(TARGET, "PART_001e")]


# Time Rewinder
class PART_002:
	action = [Bounce(TARGET)]


# Rusty Horn
class PART_003:
	action = [SetTag(TARGET, {GameTag.TAUNT: True})]


# Finicky Cloakfield
class PART_004:
	action = [Buff(TARGET, "PART_004e")]

class PART_004e:
	events = [
		OWN_TURN_BEGIN.on(Destroy(SELF))
	]


# Emergency Coolant
class PART_005:
	action = [Freeze(TARGET)]


# Reversing Switch
class PART_006:
	action = [Buff(TARGET, "PART_006a")]

class PART_006a:
	atk = lambda self, i: self._xatk
	max_health = lambda self, i: self._xhealth

	def apply(self, target):
		self._xhealth = target.atk
		self._xatk = target.health


# Whirling Blades
class PART_007:
	action = [Buff(TARGET, "PART_007e")]
