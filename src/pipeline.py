import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.manifest import ManifestStore, fingerprint_paths


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineContext:
    article_url: str
    output_dir: str
    video_title: str = ""
    cover_title: str = ""
    cover_image_index: int | None = None
    cover_kicker: str = "英超新闻 · 深度报道"
    cover_subtitle: str = ""
    cover_output_name: str = "cover.png"
    cover_orientation: str = "both"
    configuration: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)


PathResolver = Callable[[PipelineContext], list[str]]
StepAction = Callable[[PipelineContext], Awaitable[None] | None]


@dataclass(frozen=True)
class PipelineStep:
    name: str
    action: StepAction
    inputs: PathResolver
    outputs: PathResolver


@dataclass(frozen=True)
class StepExecution:
    name: str
    status: str
    duration_seconds: float = 0.0


class PipelineRunner:
    def __init__(self, context: PipelineContext, steps: list[PipelineStep]):
        if not steps:
            raise ValueError("Pipeline requires at least one step")
        names = [step.name for step in steps]
        if len(names) != len(set(names)):
            raise ValueError("Pipeline step names must be unique")
        self.context = context
        self.steps = steps
        self.store = ManifestStore(
            context.output_dir,
            context.article_url,
            configuration=context.configuration,
            prompt_versions=context.prompt_versions,
        )

    @property
    def step_names(self) -> list[str]:
        return [step.name for step in self.steps]

    def _selected_steps(
        self,
        from_step: str | None,
        to_step: str | None,
    ) -> list[PipelineStep]:
        names = self.step_names
        if from_step is not None and from_step not in names:
            raise ValueError(f"Unknown pipeline step: {from_step}")
        if to_step is not None and to_step not in names:
            raise ValueError(f"Unknown pipeline step: {to_step}")
        start = names.index(from_step) if from_step is not None else 0
        end = names.index(to_step) + 1 if to_step is not None else len(names)
        if start >= end:
            raise ValueError(
                f"Pipeline start step {from_step!r} comes after end step {to_step!r}"
            )
        return self.steps[start:end]

    def _fingerprint_inputs(self, step: PipelineStep) -> dict[str, str]:
        relative_paths = step.inputs(self.context)
        missing = [
            relative_path
            for relative_path in relative_paths
            if not (Path(self.context.output_dir) / relative_path).exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"Step {step.name} is missing inputs: {', '.join(missing)}"
            )
        return fingerprint_paths(Path(self.context.output_dir), relative_paths)

    def _fingerprint_outputs(self, step: PipelineStep) -> dict[str, str]:
        relative_paths = step.outputs(self.context)
        missing = [
            relative_path
            for relative_path in relative_paths
            if not (Path(self.context.output_dir) / relative_path).exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"Step {step.name} did not produce outputs: {', '.join(missing)}"
            )
        return fingerprint_paths(Path(self.context.output_dir), relative_paths)

    async def run(
        self,
        *,
        resume: bool = False,
        from_step: str | None = None,
        to_step: str | None = None,
        force_steps: set[str] | None = None,
        dry_run: bool = False,
    ) -> list[StepExecution]:
        force = force_steps or set()
        unknown_force = force - set(self.step_names)
        if unknown_force:
            raise ValueError(
                f"Unknown forced pipeline steps: {', '.join(sorted(unknown_force))}"
            )

        executions: list[StepExecution] = []
        for step in self._selected_steps(from_step, to_step):
            started = time.monotonic()
            inputs: dict[str, str] = {}
            try:
                try:
                    inputs = self._fingerprint_inputs(step)
                except FileNotFoundError:
                    if dry_run:
                        logger.info(
                            "Pipeline step %s: planned (inputs not generated yet)",
                            step.name,
                        )
                        executions.append(StepExecution(step.name, "planned"))
                        continue
                    raise
                can_skip = (
                    resume
                    and step.name not in force
                    and self.store.can_skip(step.name, inputs)
                )
                if dry_run:
                    status = "skipped" if can_skip else "planned"
                    logger.info("Pipeline step %s: %s", step.name, status)
                    executions.append(StepExecution(step.name, status))
                    continue
                if can_skip:
                    logger.info("Pipeline step %s: skipped (outputs unchanged)", step.name)
                    executions.append(StepExecution(step.name, "skipped"))
                    continue

                logger.info("Pipeline step %s: running", step.name)
                self.store.mark_running(step.name, inputs)
                result = step.action(self.context)
                if inspect.isawaitable(result):
                    await result
                outputs = self._fingerprint_outputs(step)
                duration = time.monotonic() - started
                self.store.mark_completed(step.name, outputs, duration)
                executions.append(StepExecution(step.name, "completed", duration))
            except Exception as error:
                if not dry_run:
                    record = self.store.get_step(step.name)
                    if record.status != "running":
                        self.store.mark_running(step.name, inputs)
                    self.store.mark_failed(
                        step.name,
                        error,
                        time.monotonic() - started,
                    )
                raise
        return executions
