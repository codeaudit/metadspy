from __future__ import annotations
from typing import Any, Callable, List, Optional, Union, Annotated, Literal
from pydantic import BaseModel, Field, model_validator
import importlib, importlib.util, pathlib, dspy


def _load(ref: str) -> Callable:
    if "::" in ref:
        path, fn = ref.split("::", 1)
        spec = importlib.util.spec_from_file_location("_tmp", pathlib.Path(path).expanduser())
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)            # type: ignore[attr-defined]
        return getattr(mod, fn)
    mod, fn = ref.rsplit(":", 1)
    return getattr(importlib.import_module(mod), fn)


class _BaseModule(BaseModel):
    name: str                              # variable name in generated code
    type: str                              # DSPy class name, e.g. "Predict" or "ReAct"
    use: str                               # Signature class to pass
    callbacks: Optional[List[str]] = None

    def _cbs(self) -> Optional[List[Callable]]:
        return [_load(c) for c in self.callbacks] if self.callbacks else None


class PredictConfig(BaseModel):
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: str | List[str] | None = None

    @model_validator(mode="after")
    def _norm(self):
        if isinstance(self.stop, str):
            self.stop = [self.stop]
        if self.temperature is not None and not (0 <= self.temperature <= 2):
            raise ValueError("temperature must be in [0,2]")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be >0")
        return self


class PredictSpec(_BaseModule):
    type: Literal["Predict"] = "Predict"
    config: PredictConfig = Field(default_factory=PredictConfig)

    def build(self, sig: type[dspy.Signature]) -> dspy.Module:
        return dspy.Predict(
            sig,
            callbacks=self._cbs(),
            **self.config.model_dump(exclude_none=True),
        )


class ReActSpec(_BaseModule):
    type: Literal["ReAct"] = "ReAct"
    tools: List[str]
    max_iters: Optional[int] = None

    def build(self, sig: type[dspy.Signature]) -> dspy.Module:
        tool_objs = [_load(t) for t in self.tools]
        kwargs: dict[str, Any] = {"tools": tool_objs}
        if self.max_iters is not None:
            kwargs["max_iters"] = self.max_iters
        if self.callbacks:
            kwargs["callbacks"] = self._cbs()
        return dspy.ReAct(sig, **kwargs)


class CodeActSpec(_BaseModule):
    type: Literal["CodeAct"] = "CodeAct"
    tools: List[str]
    max_iters: int = 5
    interpreter: Optional[str] = None

    def build(self, sig: type[dspy.Signature]) -> dspy.Module:
        tool_objs = [_load(t) for t in self.tools]
        kwargs: dict[str, Any] = {
            "tools": tool_objs,
            "max_iters": self.max_iters,
        }

        if self.interpreter:
            kwargs["interpreter"] = _load(self.interpreter)
        if self.callbacks:
            kwargs["callbacks"] = self._cbs()
        return dspy.CodeAct(sig, **kwargs)


class ChainOfThoughtSpec(_BaseModule):
    type: Literal["ChainOfThought"] = "ChainOfThought"
    rationale_field: Optional[str] = None
    rationale_field_type: str = "str"
    config: dict = Field(default_factory=dict)

    def build(self, sig: type[dspy.Signature]) -> dspy.Module:
        kwargs = dict(self.config)
        if self.rationale_field is not None:
            kwargs["rationale_field"] = self.rationale_field

        if self.rationale_field_type and self.rationale_field_type != "str":
            kwargs["rationale_field_type"] = eval(self.rationale_field_type)
    
        return dspy.ChainOfThought(sig, **kwargs)



ModuleSpec = Annotated[
    Union[PredictSpec, ReActSpec, CodeActSpec, ChainOfThoughtSpec],
    Field(discriminator="type")
]
