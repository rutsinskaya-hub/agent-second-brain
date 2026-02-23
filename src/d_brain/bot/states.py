"""Bot FSM states."""

from aiogram.fsm.state import State, StatesGroup


class DoCommandState(StatesGroup):
    """States for /do command flow."""

    waiting_for_input = State()  # Waiting for voice or text after /do


class TaskCommandState(StatesGroup):
    """States for /task command flow."""

    waiting_for_input = State()  # Waiting for task text after /task
