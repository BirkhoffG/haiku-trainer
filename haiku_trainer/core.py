# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_trainer.ipynb.

# %% ../nbs/00_trainer.ipynb 3
from __future__ import annotations
import jax, jax.numpy as jnp, jax.random as jrand
import haiku as hk
import optax
import chex
from dataclasses import dataclass
import functools as ft
from typing import Callable, Tuple, Any, Sequence, Iterable, Mapping, Dict, List, NamedTuple
import copy


# %% auto 0
__all__ = ['TrainState', 'Trainer', 'StepFn', 'DefaultStepFn', 'Callback', 'CallbackList']

# %% ../nbs/00_trainer.ipynb 5
class TrainState(NamedTuple):
    epoch: int
    step: int
    params: hk.Params
    state: hk.State
    opt_state: optax.OptState
    next_key: jrand.PRNGKey
    logs: dict = None

    def is_empty(self) -> bool:
        return self.params is None and self.opt_state is None
    
    @classmethod
    def create_empty(cls) -> TrainState:
        return cls(
            epoch=0, step=0, 
            params=None, state=None, opt_state=None, 
            next_key=None, logs=None
        )

    def __eq__(self, compare: TrainState) -> bool:
        return (self.epoch == compare.epoch) and (self.step == compare.step)

# %% ../nbs/00_trainer.ipynb 6
@dataclass
class Trainer:
    """Trainer object for training Haiku models."""
    
    transformed: hk.TransformedWithState | hk.MultiTransformedWithState
    optimizers: optax.GradientTransformation | Sequence[optax.GradientTransformation]
    rng_key: jrand.PRNGKey = None

    # callback functions
    callbacks: Sequence[Callback] = None
    step_fn: StepFn = None

    # trainer configs
    lr: float = 1e-3
    n_epochs: int = 1

    @property
    def train_state(self) -> TrainState:
        """Returns the current train state."""
        return self._train_state

    @ft.cached_property
    def num_train_batches(self) -> int:
        """Returns the number of training batches of each epoch."""
        loader = getattr(self, '_train_dataloader', None)
        if loader is None:  return 0
        else:               return len(loader)
    
    @property
    def num_train_steps(self) -> int:
        """Returns the number of training steps."""
        return self.n_epochs * self.num_train_batches
    
    @property
    def num_val_batches(self) -> int:
        """Returns the number of validation batches of each epoch."""
        loader = getattr(self, '_val_dataloader', None)
        if loader is None:  return 0
        else:               return len(loader)
    
    @property
    def num_val_steps(self):
        """Returns the number of validation steps."""
        return self.n_epochs * self.num_val_batches

    def _initialize_properties(self):
        """Initializes `train_state`."""
        if getattr(self, '_train_state', None) is None:
            self._train_state = TrainState.create_empty()
    
    def _initialize_key(self):
        """Initialize the `rng_key`."""
        if self.rng_key is None:    return jrand.PRNGKey(42) # TODO: use global
        else:                       return self.rng_key

    def _initialize_callbacks(self):
        """Initializes the callbacks."""
        if self.callbacks is None:
            self.callbacks = CallbackList()
        elif isinstance(self.callbacks, CallbackList):
            self.callbacks = self.callbacks
        elif isinstance(self.callbacks, Sequence):
            self.callbacks = CallbackList(self.callbacks)
        else:
            raise ValueError(f"Invalid callbacks. Expected `CallbackList` or `Sequence[Callback]`.")

        self.callbacks.init_trainer(self)

    def _initialize_step_fn(self):
        """Initializes step fns."""
        if self.step_fn is None:
            self.step_fn = DefaultStepFn(trainer=self)
        else:
            if isinstance(self.step_fn, StepFn):
                self.step_fn.init_trainer(self)
            else:
                raise ValueError(f"Invalid `Trainer.step_fn`. Expected `StepFn`, but got `{type(self.step_fn)}`.")
    
    def _initialize(self):
        """Initializes the trainer."""
        self._initialize_properties()
        self._initialize_key()
        self._initialize_callbacks()
        self._initialize_step_fn()

    def _update_loader(self, loader_name: str, loader=None):
        if getattr(self, loader_name, None) is None:
            setattr(self, loader_name, loader)
        if loader is not None:
            setattr(self, loader_name, loader)
    
    def _initialize_loaders(
        self, 
        train_dataloader, 
        val_dataloader=None, 
        test_dataloader=None
    ):
        """Initialize and hook dataloaders to the trainer."""
        self._update_loader('_train_dataloader', train_dataloader)
        self._update_loader('_val_dataloader', val_dataloader)
        self._update_loader('_test_dataloader', test_dataloader)
        
    def _run_callbacks(
        self, 
        hook_name: str, # Should be "on_{train/val}_{epoch/batch}_{begin/end}"
        **cb_kwargs # kwargs for the callback function
    ):
        """Runs the callback functions for the given hook.
        Note that callback functions do not change the `train_state`.
        """
        hook_fn = getattr(self.callbacks, hook_name, None)
        if hook_fn is not None:
            hook_fn(self.train_state, **cb_kwargs)

    def _run_step_fn(
        self, 
        step_name: str, 
        validate: bool = False,
        **fn_kwargs # kwargs for the step function
    ):
        """Runs the step function for the given step name.
        Note that step functions change the `train_state`.
        """
        step_fn = getattr(self.step_fn, step_name)
        train_state = step_fn(self.train_state, **fn_kwargs)

        if validate and train_state == self.train_state:
            raise ValueError(f"Train state is not updated after `{step_name}`.")
        self.update_train_state(train_state)

    def update_train_state(self, train_state: TrainState = None, **kwargs):
        """Updates the `train_state`."""
        if train_state is None and kwargs == {}:
            raise ValueError("Either `train_state` or `kwargs` must be provided.")
        if train_state is None:
            train_state = self.train_state._replace(**kwargs)
        self._train_state = train_state

    def fit(self, train_dataloader, val_dataloader=None):
        self._initialize()
        self._initialize_loaders(train_dataloader, val_dataloader)
        
        self._run_callbacks("on_train_begin")
        for epoch in range(self.n_epochs):
            self._run_callbacks("on_epoch_begin")
            for batch in train_dataloader:
                self._run_callbacks("on_train_batch_begin")
                # Initialize the train state if it is not initialized
                if self.train_state.is_empty():
                    self._run_step_fn("init_step", batch=batch)
                self._run_step_fn("train_step", batch=batch)
                self._run_callbacks("on_train_batch_end")
            self._run_callbacks("on_epoch_end")

            if val_dataloader is not None:
                self._run_callbacks("on_val_begin")
                for batch in val_dataloader:
                    self._run_callbacks("on_val_batch_begin")
                    self._run_step_fn("val_step", batch=batch)
                    self._run_callbacks("on_val_batch_end")
                self._run_callbacks("on_val_end")

            # self._run_callbacks("on_epoch_end")
            self._run_step_fn("epoch_step", batch=None)
        
        self._run_callbacks("on_train_end")

    __ALL__ = ['fit']


# %% ../nbs/00_trainer.ipynb 8
class StepFn:
    def __init__(self, trainer: Trainer=None, *args, **kwargs) -> None:
        if trainer is not None:
            self.init_trainer(trainer)

    def init_trainer(self, trainer: Trainer):
        self._trainer = trainer

    @property
    def trainer(self): return self._trainer

    @property
    def transformed(self): return self.trainer.transformed

    forward = transformed
    
    @property
    def optimizers(self): return self.trainer.optimizers

    def init_step(self, train_state: TrainState, batch: Tuple[jax.Array, ...]) -> TrainState:
        key1, next_key = jrand.split(self._init_key())
        
        params, state = self._init_params_and_state(key1, batch[0])
        opt_states = self._init_opt_state(params)
        return TrainState(
            epoch=0, step=0, params=params, state=state, 
            opt_state=opt_states, next_key=next_key,
        )
    
    def epoch_step(self, train_state: TrainState, batch=None) -> TrainState:
        return train_state._replace(epoch=train_state.epoch+1)
    
    def train_step(self, train_state: TrainState, batch: Tuple[jax.Array, ...]) -> TrainState:
        raise NotImplementedError
    
    def val_step(self, train_state: TrainState, batch: Tuple[jax.Array, ...]) -> TrainState:
        raise NotImplementedError
    
    def _init_key(self):
        if self.trainer.rng_key is None:
            return jrand.PRNGKey(0)
        elif isinstance(self.trainer.rng_key, jrand.PRNGKey):
            return self.trainer.rng_key
        else:
            raise ValueError(f"Invalid rng_key. Expected `jax.random.PRNGKey`.")

    def _init_params_and_state(self, key: jrand.PRNGKey, xs: jax.Array):
        params, state = self.transformed.init(key, xs)
        return params, state

    def _init_opt_state(self, params: hk.Params):
        if isinstance(self.optimizers, optax.GradientTransformation):
            return self.optimizers.init(params) 
        else:
            raise ValueError(f"Invalid optimizers. Expected `optax` optimizers.")


# %% ../nbs/00_trainer.ipynb 9
class DefaultStepFn(StepFn):

    @ft.partial(jax.jit, static_argnums=(0,))
    def train_step(self, train_state: TrainState, batch: Tuple[jax.Array, ...]) -> TrainState:
        def loss_fn(params: hk.Params):
            logits, new_state = self.transformed.apply(
                params, state,
                rng_key, # <== rng
                inputs, is_training=True # <== inputs
            )
            loss = optax.softmax_cross_entropy_with_integer_labels(logits, labels).mean()
            return (loss, new_state)
        
        inputs, labels = batch
        rng_key, next_key = jrand.split(train_state.next_key)
        state = train_state.state
        (loss, new_state), grads = jax.value_and_grad(loss_fn, has_aux=True)(train_state.params)
        updates, new_opt_state = self.optimizers.update(
            grads, train_state.opt_state, train_state.params)
        new_params = optax.apply_updates(train_state.params, updates)
        return TrainState(
            epoch=train_state.epoch,
            step=train_state.step + 1,
            params=new_params,
            state=new_state,
            opt_state=new_opt_state,
            next_key=next_key,
            logs={'train/loss': loss}
        )
    
    def val_step(self, train_state: TrainState, batch: Tuple[jax.Array, ...]) -> TrainState:
        inputs, labels = batch
        rng_key, next_key = jrand.split(train_state.next_key)
        logits, _ = self.transformed.apply(
            train_state.params, train_state.state,
            rng_key, # <== rng
            inputs, is_training=False # <== inputs
        )
        loss = optax.softmax_cross_entropy_with_integer_labels(logits, labels).mean()
        acc = (jnp.argmax(logits, axis=-1) == labels).mean()
        logs = {'val/loss': loss, "val/accuracy": acc}

        return train_state._replace(
            step=train_state.step + 1,
            next_key=next_key, logs=logs
        )

    

# %% ../nbs/00_trainer.ipynb 11
class Callback:
    _trainer: Trainer = None

    @property
    def trainer(self) -> Trainer: 
        return self._trainer

    @trainer.setter
    def trainer(self, trainer: Trainer): 
        self._trainer = trainer
    
    def init_trainer(self, trainer: Trainer) -> Callback:
        self.trainer = trainer
        return self

    def on_epoch_begin(self, state: TrainState): pass

    def on_epoch_end(self, state: TrainState): pass

    def on_train_batch_begin(self, state: TrainState): pass

    def on_train_batch_end(self, state: TrainState): pass

    def on_train_begin(self, state: TrainState): pass

    def on_train_end(self, state: TrainState): pass

    def on_val_batch_begin(self, state: TrainState): pass

    def on_val_batch_end(self, state: TrainState): pass

    def on_val_begin(self, state: TrainState): pass

    def on_val_end(self, state: TrainState): pass
    
    # __all__ = [
    #     "on_epoch_begin",
    #     "on_epoch_end",
    #     "on_predict_batch_begin",
    #     "on_predict_batch_end",
    #     "on_predict_begin",
    #     "on_predict_end",
    #     "on_test_batch_begin",
    #     "on_test_batch_end",
    #     "on_test_begin",
    #     "on_test_end",
    #     "on_train_batch_begin",
    #     "on_train_batch_end",
    #     "on_train_begin",
    #     "on_train_end",
    # ]

# %% ../nbs/00_trainer.ipynb 12
class CallbackList:

    def __init__(
        self,
        callbacks: List[Callback] = None,
        add_history: bool = True,
        add_progbar: bool = True,
        trainer: Trainer = None,
        **kwargs
    ):
        self.callbacks = callbacks if callbacks else []
        self._check_callbacks()
        self._add_default_callbacks(add_history, add_progbar)

        if trainer is not None:
            self.init_trainer(trainer)

    def append(self, callback: Callback):
        self.callbacks.append(callback)

    def __iter__(self):
        return iter(self.callbacks)

    def _check_callbacks(self):
        for cb in self.callbacks:
            if not isinstance(cb, Callback):
                raise TypeError(
                    "All callbacks must be instances of `Callback` "
                    f"got {type(cb).__name__}."
                )

    def _add_default_callbacks(self, add_history: bool, add_progbar: bool):
        pass

    def init_trainer(self, trainer: Trainer):
        for callback in self.callbacks:
            callback.init_trainer(trainer)
        
    def _call_hook(self, hook_name, state):
        for callback in self.callbacks:
            batch_hook = getattr(callback, hook_name)
            batch_hook(state)

    def on_epoch_begin(self, state: TrainState):
        self._call_hook("on_epoch_begin", state)

    def on_epoch_end(self, state: TrainState):
        self._call_hook("on_epoch_end", state)

    def on_train_batch_begin(self, state: TrainState):
        self._call_hook("on_train_batch_begin", state)

    def on_train_batch_end(self, state: TrainState):
        self._call_hook("on_train_batch_end", state)

    def on_train_begin(self, state: TrainState):
        self._call_hook("on_train_begin", state)

    def on_train_end(self, state: TrainState):
        self._call_hook("on_train_end", state)

    def on_val_batch_begin(self, state: TrainState):
        self._call_hook("on_val_batch_begin", state)

    def on_val_batch_end(self, state: TrainState):
        self._call_hook("on_val_batch_end", state)

    def on_val_begin(self, state: TrainState):
        self._call_hook("on_val_begin", state)

    def on_val_end(self, state: TrainState):
        self._call_hook("on_val_end", state)

# %% ../nbs/00_trainer.ipynb 15
def make_hk_module(output_size: int = 2):
    """Creates a Haiku module with a linear layer and batchnorm."""
    def model(x, is_training=True):
        return hk.BatchNorm(True, True, 0.9)(
            hk.Linear(output_size)(x), is_training=is_training)
    
    return hk.transform_with_state(model)
