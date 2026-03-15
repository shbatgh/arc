# Python Advanced Topics for BioVision

## Purpose

This file is a companion to:

- `PYTHON_PERFORMANCE_QUICKSTART.md`
- `PYTHON_PERFORMANCE_IMPROVEMENTS.md`

It goes deeper on the parts of Python that matter once you move past "basic scripting" and start doing real performance-oriented refactors:

- multithreading
- multiprocessing
- concurrency
- `asyncio`
- typing
- lambdas and advanced function features
- practical data structures
- Python quirks that cause bugs or wasted time

This is written for someone who already thinks like an experienced developer and wants the Python-specific mental model, not beginner material.

## Start With The Right Decision Table

Before going deep into the details, use this as the default decision guide for this repo.

| Problem | Best default | Why |
| --- | --- | --- |
| CPU-heavy Python loops | `ProcessPoolExecutor` | bypasses the GIL |
| File I/O or light image loading | threads | waiting dominates |
| Thousands of network/socket tasks | `asyncio` | low-overhead cooperative concurrency |
| CPU-heavy NumPy/SciPy work | benchmark threads vs processes | some native code releases the GIL |
| Background orchestration of subprocesses | `asyncio` or threads | mostly waiting |
| Fine-grained shared mutable state | avoid if possible | Python concurrency gets harder fast |

For BioVision specifically:

- threads are useful for I/O and orchestration
- processes are the main tool for true CPU parallelism
- `asyncio` is usually not the right core architecture for the pipeline

## Concurrency vs Parallelism

These words are related but not identical.

### Concurrency

Concurrency means multiple tasks can make progress during the same period of time.

Examples:

- multiple threads taking turns
- multiple `asyncio` tasks yielding to each other
- multiple processes running independently

### Parallelism

Parallelism means multiple tasks are actually executing at the same time on different CPU cores.

Examples:

- multiple OS processes on multiple cores
- some native C or C++ extensions doing parallel work internally

### Why this distinction matters in Python

You can have concurrency without much parallel speedup if:

- work is CPU-heavy
- the work is in Python bytecode
- the GIL prevents multiple threads from executing Python code at once

That is why "just use threads" is often wrong for CPU-bound Python.

## The GIL: What It Is and What It Means

CPython, the standard Python implementation, has a Global Interpreter Lock.

Very short version:

- one thread executes Python bytecode at a time in a process
- this simplifies memory management and interpreter internals
- it limits CPU scaling for pure Python multithreaded code

### What the GIL does not mean

It does not mean threads are useless.

Threads still help when:

- code spends time waiting on disk
- code spends time waiting on network
- code spends time in C extensions that release the GIL

Examples of C-backed code that may release the GIL:

- NumPy operations
- SciPy operations
- some image libraries
- some compression and serialization libraries

The rule is not "threads are bad." The rule is "do not assume threads speed up CPU-heavy Python loops."

## Multithreading In Practice

## When threads are a good fit

Threads are a good fit when each unit of work mostly waits.

Examples in this repo:

- walking directories and opening many files
- reading images from disk
- writing many output files
- orchestrating external tools

## `ThreadPoolExecutor`

This is the easiest standard way to use threads.

```python
from concurrent.futures import ThreadPoolExecutor

def load_image(path: str):
    with Image.open(path) as img:
        return np.asarray(img)

with ThreadPoolExecutor(max_workers=8) as ex:
    arrays = list(ex.map(load_image, image_paths))
```

This is appropriate if:

- loading dominates
- image decoding is not the bottleneck
- you are not doing heavy Python processing in the worker

## Shared state and threads

Threads share process memory.

That is convenient because:

- you do not need to pickle data to send it to another thread

But it is dangerous because:

- multiple threads can mutate the same object
- bugs become timing-dependent

### Use locks sparingly

```python
import threading

lock = threading.Lock()

with lock:
    shared_dict[key] = value
```

Good use:

- protecting a small critical section

Bad use:

- wrapping most of a worker body in a lock

If you lock too much, you lose the concurrency benefit.

## Other synchronization primitives

Useful ones:

- `Lock`
- `RLock`
- `Event`
- `Condition`
- `Semaphore`
- `queue.Queue`

### `queue.Queue`

This is the standard producer-consumer structure for threads.

```python
from queue import Queue
from threading import Thread

q = Queue()

def worker():
    while True:
        item = q.get()
        if item is None:
            q.task_done()
            break
        process(item)
        q.task_done()
```

This is better than having many threads mutate one shared list.

## Thread pitfalls

### Pitfall 1: assuming built-in operations make larger workflows thread-safe

Some individual operations are atomic enough for internal interpreter safety, but that does not make compound logic thread-safe.

Bad assumption:

```python
if key not in shared:
    shared[key] = value
```

Another thread may race between those two lines.

### Pitfall 2: mutable shared caches

A shared dict cache can be fine, but once multiple threads populate it lazily, you need to reason about races.

### Pitfall 3: exceptions disappearing

With futures, exceptions occur in worker threads and are re-raised when you access the future result.

```python
future.result()
```

If you never consume the future, you may miss failures.

## Multiprocessing: The Main Parallel Tool

If you want CPU scaling for Python-heavy work, use processes.

## Why processes work

Each process has:

- its own interpreter
- its own GIL
- its own memory space

That means CPU-heavy Python work can truly run in parallel across cores.

## `ProcessPoolExecutor`

```python
from concurrent.futures import ProcessPoolExecutor

def build_mesh(cell):
    return get_solid_mesh_objs(cell)

with ProcessPoolExecutor() as ex:
    all_meshes = list(ex.map(build_mesh, cells3D))
```

This is the high-level tool you will probably want first.

## Process costs

Processes are not free.

You pay for:

- pickling arguments
- pickling results
- memory duplication
- worker startup

That means:

- coarse work units are good
- tiny work units are bad

Good task granularity for this repo:

- one timepoint
- one `Cell3D`
- one large batch of cells

Bad task granularity:

- one outline
- one short loop body
- one tiny geometry helper

## Start method differences

Depending on platform, Python multiprocessing can start workers with different methods:

- `fork`
- `spawn`
- `forkserver`

The practical takeaway:

- on Linux, `fork` is common and can be fast
- on macOS and Windows, `spawn` behavior matters more
- with `spawn`, everything needed by the worker must be importable at module scope

That means:

- worker functions should be top-level functions
- avoid relying on interactive or notebook-only state
- avoid giant implicit globals

## Use `if __name__ == "__main__":`

When starting processes in scripts, this matters.

```python
if __name__ == "__main__":
    main()
```

Without it, child process startup can recursively re-execute module code in unwanted ways, especially with `spawn`.

## Process-safe patterns

Good:

- pass immutable or self-contained data
- return plain results
- aggregate in the parent

Bad:

- workers mutating shared global state
- workers writing to the same file handle
- lots of cross-process chatter

## `asyncio`: What It Is Actually For

`asyncio` is cooperative concurrency around an event loop.

It is best for:

- network servers and clients
- many sockets
- high-latency external operations
- task orchestration where most tasks wait

It is not a magic speed feature for CPU-heavy pipelines.

## Core concepts

### Coroutine

A coroutine is a function defined with `async def`.

```python
async def fetch():
    ...
```

Calling it does not run it immediately. It returns a coroutine object.

### `await`

`await` suspends the current coroutine until the awaited operation completes.

```python
result = await other_coro()
```

### Event loop

The event loop schedules coroutines and resumes them when their awaited work is ready.

## Minimal example

```python
import asyncio

async def work(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"done {name}"

async def main() -> None:
    results = await asyncio.gather(
        work("a", 1.0),
        work("b", 1.0),
    )
    print(results)

asyncio.run(main())
```

This finishes in about one second, not two, because both tasks spend their time waiting.

## Why `asyncio` usually does not help BioVision core compute

Most heavy stages in BioVision are:

- image processing
- geometry
- Python loops
- mesh construction

Those are CPU-heavy. `asyncio` does not make CPU-heavy Python code parallel.

If you do this:

```python
async def heavy():
    big_cpu_loop()
```

the event loop is still blocked while `big_cpu_loop()` runs.

## Where `asyncio` might still be useful

Potentially useful for:

- orchestrating many subprocesses
- building a service wrapper around the pipeline
- monitoring files or jobs
- coordinating a UI with long-running background tasks

But it is not the first concurrency tool for this repo.

## `asyncio` tools you should know anyway

### `asyncio.create_task`

Starts a coroutine concurrently under the loop.

```python
task = asyncio.create_task(work())
result = await task
```

### `asyncio.gather`

Waits for multiple coroutines.

```python
results = await asyncio.gather(coro1(), coro2(), coro3())
```

### `asyncio.Semaphore`

Limits concurrent tasks.

```python
sem = asyncio.Semaphore(10)

async with sem:
    await do_io()
```

### `asyncio.to_thread`

Runs a blocking function in a thread from async code.

```python
result = await asyncio.to_thread(blocking_function, arg1, arg2)
```

Useful when you have an async application shell but still need a blocking library call.

### Timeouts

```python
async with asyncio.timeout(5):
    await maybe_slow()
```

### Cancellation

Tasks can be cancelled. Well-behaved async code should not swallow `CancelledError` carelessly.

## Mixing `asyncio` and processes

You can combine them.

Common pattern:

- `asyncio` orchestrates jobs
- CPU-heavy work is delegated to a process pool

But unless you are building a service or UI, that is probably more architecture than this repo needs.

## Typing: The Parts That Are Worth Learning

Type hints in Python are mostly for:

- readability
- IDE help
- static analysis
- refactor safety

They are not mainly for runtime performance.

## Type aliases

These are very useful for shape-heavy code.

```python
from typing import TypeAlias
import numpy as np

Color: TypeAlias = tuple[int, int, int]
Point2D: TypeAlias = tuple[float, float]
Point3D: TypeAlias = tuple[float, float, float]
Outline: TypeAlias = np.ndarray
```

This is a good fit for this repo because the same structures appear repeatedly.

## `Sequence` vs `list`

Use the most general type you actually need.

```python
from collections.abc import Sequence

def centroid(points: Sequence[Point2D]) -> Point2D:
    ...
```

Use:

- `Sequence[T]` if you only need indexing and length
- `Iterable[T]` if you only iterate
- `list[T]` only if you specifically need list methods or mutability

This is the typing equivalent of writing a better interface.

## `Protocol`

Use `Protocol` when you care about behavior, not inheritance.

```python
from typing import Protocol

class HasCenter3D(Protocol):
    center_xyz: np.ndarray
    max_match_radius: float
```

Any object with those attributes matches structurally.

This is useful when refactoring matching code to operate on any geometry-bearing cell-like object.

## `TypedDict`

Use this for dict-shaped records.

```python
from typing import TypedDict

class MeshRecord(TypedDict):
    vertices: list[list[float]]
    faces: list[list[int]]
    color: tuple[int, int, int]
    name: str
```

This is useful when your serialized mesh objects are dicts with a known schema.

## `Literal`

Useful when values come from a small fixed set.

```python
from typing import Literal

Axis = Literal["x", "y", "z"]
Mode = Literal["fast", "balanced", "high"]
```

This helps catch bad string arguments early.

## `Callable`

Use this when passing functions around.

```python
from collections.abc import Callable

MetricFn = Callable[[np.ndarray], float]
```

## `TypeVar`

Use `TypeVar` when writing generic helpers.

```python
from typing import TypeVar

T = TypeVar("T")

def first(xs: list[T]) -> T:
    return xs[0]
```

For this repo, you probably do not need heavy generic programming. Use it when it makes signatures clearer, not to be clever.

## `Optional` vs `| None`

Modern Python usually prefers:

```python
Point3D | None
```

instead of:

```python
Optional[Point3D]
```

Both are fine.

## Static checking

If you start pushing more typing into the repo, use a type checker.

Common choices:

- `mypy`
- `pyright`

The value here is high when changing nested data structures.

## Advanced Function Features

Python functions are first-class objects.

That means they can be:

- stored in variables
- passed as arguments
- returned from other functions
- captured by closures

## Lambdas

Python lambdas are anonymous functions with a single expression body.

```python
key_fn = lambda p: p[0]
points.sort(key=key_fn)
```

### What lambdas are good for

- very small key functions
- short one-off adapters

Good:

```python
points.sort(key=lambda p: p[0])
```

### What lambdas are bad for

- anything nontrivial
- multi-step logic
- code you may want to debug or reuse

Bad:

```python
foo = lambda x: some_complicated_branching_expression(...)
```

Use `def` instead.

### Lambdas are not special-performance functions

They are not faster than normal functions.

They also have the same closure behavior and the same late-binding traps.

## Closures and late binding

Closures capture variables, not snapshots of values.

Classic trap:

```python
funcs = []
for i in range(3):
    funcs.append(lambda: i)

print([f() for f in funcs])   # [2, 2, 2]
```

Each lambda sees the same final `i`.

Fix:

```python
funcs = []
for i in range(3):
    funcs.append(lambda i=i: i)
```

or just use a normal helper function.

## Default argument evaluation

Default arguments are evaluated once, at function definition time.

Bad:

```python
def add_point(p, acc=[]):
    acc.append(p)
    return acc
```

Each call reuses the same list.

Good:

```python
def add_point(p, acc=None):
    if acc is None:
        acc = []
    acc.append(p)
    return acc
```

This is one of Python's most famous quirks.

## `*args` and `**kwargs`

These collect positional and keyword arguments.

```python
def log_args(*args, **kwargs):
    print(args, kwargs)
```

Useful for:

- wrappers
- decorators
- forwarding arguments

Do not overuse them in core computational code because they weaken readability and typing precision.

## Keyword-only and positional-only arguments

Keyword-only:

```python
def build_mesh(cell, *, smooth_iters=3, num_points=96):
    ...
```

This is useful for configuration-heavy functions because it forces explicit call sites.

Positional-only:

```python
def scale(x, /, factor):
    ...
```

You probably will not need positional-only much here.

## `functools.partial`

Useful when you want to bind some arguments up front.

```python
from functools import partial

fast_mesh = partial(build_mesh, smooth_iters=1, num_points=48)
```

This is often cleaner than a lambda wrapper.

## Decorators

A decorator wraps a function.

```python
from functools import wraps
from time import perf_counter

def timed(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            print(f"{fn.__name__}: {perf_counter() - t0:.3f}s")
    return wrapper
```

Useful for:

- timing
- logging
- caching

Do not overdecorate hot code just to be clever. Wrapping layers still add complexity.

## Generators

Generators produce values lazily with `yield`.

```python
def rows():
    for cell in cells:
        yield make_row(cell)
```

This is useful when:

- streaming CSV rows
- walking large datasets
- avoiding building giant intermediate lists

### Generator expressions

```python
total = sum(x * x for x in values)
```

This avoids constructing a full list.

### Iterator exhaustion

A generator can be consumed once.

```python
g = (x for x in range(3))
list(g)   # [0, 1, 2]
list(g)   # []
```

This is a common bug source.

## `functools.lru_cache`

Useful for pure functions with repeated calls on the same inputs.

```python
from functools import lru_cache

@lru_cache(maxsize=None)
def expensive_lookup(key):
    ...
```

This is not a blanket optimization. It helps only when:

- the function is pure
- repeated inputs occur
- argument objects are hashable

For this repo, cache geometry derived from immutable identifiers or pre-normalized tuples, not mutable arrays.

## `singledispatch`

Useful if you want one function name with different behaviors by input type.

```python
from functools import singledispatch

@singledispatch
def to_array(x):
    raise TypeError(type(x))
```

Probably not a first-priority tool here, but good to know.

## Data Structures That Actually Matter

Python performance is often dominated by choosing the right built-in container.

## `list`

Best for:

- ordered collections
- append-heavy stacks
- index access

Good properties:

- amortized O(1) append
- O(1) index access

Bad at:

- popping from the front
- membership tests on large collections

## `tuple`

Best for:

- fixed-size records
- immutable coordinate-like values
- dict keys
- cache keys

Good because:

- immutable
- hashable if contents are hashable
- slightly lighter-weight than list

Use tuples for:

- colors
- points that should not mutate

Use arrays for heavy numeric work.

## `dict`

Best for:

- mapping IDs to objects
- color-to-outlines mapping
- caches
- lookup tables

Important facts:

- average O(1) lookup
- preserves insertion order in modern Python

Great for this repo:

- `dict[color] -> list[Cell]`
- `dict[cell_id] -> Cell3D`

## `set`

Best for:

- membership tests
- uniqueness

This repo currently uses sets in connected-component extraction. That works functionally, but NumPy/SciPy labeling is likely a better performance fit for large image-derived components.

## `deque`

From `collections`.

Best for:

- queue behavior
- fast append/pop on both ends

```python
from collections import deque

q = deque()
q.append(x)
item = q.popleft()
```

Better than list for BFS queues.

## `defaultdict`

Great when grouping.

```python
from collections import defaultdict

groups = defaultdict(list)
groups[color].append(component)
```

This is cleaner than repeated `if key not in dict`.

## `Counter`

Good for counting, not a general optimization tool.

```python
from collections import Counter
```

Probably not central to this repo.

## `heapq`

Good for priority queues or top-k problems.

```python
import heapq
```

You may use this if you ever want best-first candidate selection without sorting an entire list.

## `bisect`

Good for maintaining sorted arrays or binary searching sorted sequences.

Potentially useful in geometry code when repeatedly querying sorted scalar values.

## `array.array`

Numeric standard-library array type.

Usually not the best choice if you already use NumPy heavily. NumPy is the better general numeric container for this repo.

## `dataclass` vs `dict` vs tuple for records

Use:

- tuple for tiny fixed return values
- dict for schema-flexible serialized records
- dataclass for structured in-memory domain objects

For core logic, dataclasses are usually the clearest choice.

## Python Quirks That Matter

## `is` vs `==`

`is` checks identity.

`==` checks value equality.

```python
a = [1, 2]
b = [1, 2]

a == b   # True
a is b   # False
```

Use `is` mainly for:

- `None`
- singleton sentinels

```python
if value is None:
    ...
```

Do not use `is` for ordinary value comparison.

## Truthiness

Many values are falsey:

- `None`
- `0`
- `0.0`
- `""`
- `[]`
- `{}`
- `set()`

This is convenient, but it can hide bugs.

Example:

```python
if pos:
    ...
```

That works if `pos` is `None` or a tuple, but it is less explicit than:

```python
if pos is not None:
    ...
```

Prefer the explicit form when `None` has semantic meaning.

## List multiplication aliasing

Classic bug:

```python
rows = [[]] * 3
rows[0].append(1)
print(rows)   # [[1], [1], [1]]
```

All entries refer to the same list.

Correct:

```python
rows = [[] for _ in range(3)]
```

## In-place mutation with `+=`

`+=` may mutate in place or create a new object depending on the type.

With lists:

```python
a = [1]
b = a
a += [2]
```

`a` is mutated, so `b` sees the change.

With tuples:

```python
a = (1,)
a += (2,)
```

This creates a new tuple.

Know the type you are working with.

## Exception handling

Bad:

```python
except:
    pass
```

This catches too much, including keyboard interrupts and system-exit paths.

Better:

```python
except Exception as exc:
    ...
```

And often better still:

- catch narrower exception types
- log enough context

For performance-sensitive code, broad exception swallowing can also hide hotspots and data issues.

## Comprehension scope

In modern Python, comprehension loop variables have their own scope.

```python
x = 10
vals = [x for x in range(3)]
print(x)   # 10
```

That differs from some older Python behavior and from how a plain `for` loop behaves.

## `for`-`else`

Python has `for`-`else`.

The `else` block runs if the loop did not `break`.

```python
for item in items:
    if ok(item):
        break
else:
    print("not found")
```

Useful sometimes, but many developers find it opaque. Use only when it reads clearly.

## Sort stability

Python sorts are stable.

That means if two items compare equal under the key, their original relative order is preserved.

This is useful for multi-pass sorting:

```python
items.sort(key=lambda x: x.secondary)
items.sort(key=lambda x: x.primary)
```

The final result is sorted by primary, then by secondary.

## Iterating while mutating

Avoid mutating a list while iterating over it unless you are very deliberate.

Bad:

```python
for x in xs:
    if should_remove(x):
        xs.remove(x)
```

This skips elements unpredictably.

Prefer:

```python
xs = [x for x in xs if not should_remove(x)]
```

or build a new list.

## Hashability

Mutable objects are usually not hashable.

Examples:

- list is not hashable
- dict is not hashable
- tuple is hashable only if its contents are hashable

This matters for:

- dict keys
- set membership
- caching

## Floating-point comparisons

Do not assume exact equality for computed floats.

Use:

```python
import math

math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)
```

or:

```python
np.allclose(arr1, arr2, atol=1e-6)
```

This matters in geometry and mesh code.

## Scope rules and `nonlocal`

Python uses LEGB scope:

- Local
- Enclosing
- Global
- Builtins

If you assign to a name in a function, Python treats it as local unless declared otherwise.

```python
count = 0

def bad():
    count += 1   # UnboundLocalError
```

Fix with:

```python
global count
```

or better, avoid globals.

For closures:

```python
def outer():
    count = 0
    def inner():
        nonlocal count
        count += 1
```

`nonlocal` is for variables in an enclosing function scope.

## Globals: convenient but expensive architecturally

This repo already has some module-level mutable state. That is common in scripts, but it makes:

- testing harder
- multiprocessing trickier
- reasoning about concurrency harder

For refactors, prefer explicit inputs and return values over hidden module state.

## Python Performance Quirks

## Attribute lookups cost more than local variables

In tight loops, repeated attribute access can matter.

```python
append = out.append
for item in items:
    append(transform(item))
```

This kind of micro-optimization is real, but it is secondary. Use it only after you have fixed bigger issues like algorithm choice and copying.

## Function call overhead is nontrivial

Very small helper functions called millions of times can matter in Python.

That does not mean "inline everything." It means:

- keep the hottest inner loops simple
- push work into vectorized NumPy or compiled SciPy calls where possible

## Comprehensions are usually good

List comprehensions are often clearer and faster than manual append loops.

```python
centers = [cell.center_xyz for cell in cells]
```

But if you need laziness, use a generator.

## `sum(listcomp)` vs `sum(genexpr)`

If you do not need the intermediate list, use the generator expression.

```python
total = sum(x * x for x in values)
```

## Memory matters

In Python, speed and memory are often linked because allocating lots of objects is expensive.

This is why:

- arrays help
- `slots` help
- avoiding `deepcopy` helps
- avoiding huge temporary dict/list structures helps

## Repo-Specific Concurrency Guidance

These are the practical conclusions for BioVision.

## Good candidates for threads

- image loading from disk
- writing multiple output files
- orchestration wrappers

## Good candidates for processes

- per-timepoint stack matching
- per-color or per-batch animation matching
- per-cell mesh generation

## Bad candidates for `asyncio`

- contour sorting
- BFS or connected-component extraction
- geometry-heavy mesh generation
- all-pairs matching loops

## Good candidates for `asyncio`

- a future web service around the pipeline
- job queue orchestration
- nonblocking subprocess management

## Typing Guidance For BioVision

If you decide to add types while refactoring, start with these.

```python
from typing import TypeAlias, Literal, TypedDict
import numpy as np

Color: TypeAlias = tuple[int, int, int]
Point2D: TypeAlias = tuple[float, float]
Point3D: TypeAlias = tuple[float, float, float]
Outline2D: TypeAlias = np.ndarray
Outline3D: TypeAlias = np.ndarray
Axis = Literal["x", "y", "z"]
Quality = Literal["fast", "balanced", "high"]

class MeshRecord(TypedDict):
    vertices: list[list[float]]
    faces: list[list[int]]
    color: Color
    name: str
```

That alone will already make many signatures clearer.

## Advanced Patterns Worth Knowing

## Sentinel objects

Sometimes `None` is a valid value and you need a distinct "missing" marker.

```python
MISSING = object()

def get_value(x=MISSING):
    if x is MISSING:
        ...
```

This is cleaner than overloading `None` for too many meanings.

## Context managers

You can define your own with `contextlib`.

```python
from contextlib import contextmanager
from time import perf_counter

@contextmanager
def timed(label: str):
    t0 = perf_counter()
    try:
        yield
    finally:
        print(f"{label}: {perf_counter() - t0:.3f}s")
```

Usage:

```python
with timed("mesh generation"):
    build_meshes()
```

This is a clean pattern for timing refactors.

## `enumerate`, `zip`, and unpacking

These are small but important Python idioms.

```python
for i, item in enumerate(items):
    ...

for a, b in zip(xs, ys):
    ...
```

They are clearer than manual index tracking in many cases.

## Structural pattern matching

Modern Python has `match`.

```python
match mode:
    case "fast":
        ...
    case "balanced":
        ...
    case "high":
        ...
```

This can be useful for mode dispatch, but do not force it where a simple dict or `if` is clearer.

## What To Learn First From This File

If you want the highest return on time, study these sections first:

1. GIL and the threads vs processes decision
2. process pool rules and work granularity
3. typing with `TypeAlias`, `Literal`, and `TypedDict`
4. closures, lambdas, and default-argument quirks
5. lists, dicts, sets, and `deque`
6. the major Python bug patterns in the quirks section

That is enough to avoid most painful mistakes while refactoring this codebase.

## Final Position

For this repo, the advanced Python takeaway is:

- think carefully about mutability
- keep data structures explicit
- use typing to stabilize refactors
- use processes for CPU parallelism
- use threads for waiting
- use `asyncio` only when the workload is fundamentally async
- use lambdas sparingly
- assume Python quirks are real until proven otherwise

Once you internalize those, the language stops fighting you and becomes a practical systems glue language with strong numerical tooling.
