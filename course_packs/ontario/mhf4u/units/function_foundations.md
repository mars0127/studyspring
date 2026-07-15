# Function foundations and transformations

## Why this matters

Functions let you describe how one quantity depends on another. In Advanced Functions, you will use their features to model change, solve problems, and prepare for calculus.

## Learning goals

- Identify a function's domain, range, intercepts, zeros, extrema, and intervals of increase or decrease.
- Predict a transformation from an equation.
- Find and check an inverse when it exists.
- Evaluate and interpret a composition of functions.

## Prerequisite review

A function assigns exactly one output to every input in its domain. Use the vertical-line test on a graph: if a vertical line crosses it more than once, the relation is not a function.

## Concept explanation

For `g(x) = a f(k(x - d)) + c`:

- `d` shifts the graph right when positive.
- `c` shifts it up when positive.
- a negative `a` reflects across the x-axis; `|a| > 1` stretches vertically.
- a negative `k` reflects across the y-axis; `|k| > 1` compresses horizontally.

Write transformations in a consistent order and test one familiar point to avoid reversing a horizontal change.

## Worked example

Let `f(x) = x²`. Describe `g(x) = -2(x - 3)² + 5`.

Start with the parent parabola. Move it 3 units right, stretch it vertically by a factor of 2, reflect it in the x-axis, then move it 5 units up. The vertex is `(3, 5)` and the parabola opens downward.

## Inverses

An inverse reverses a function's input and output. A function needs to be one-to-one on the chosen domain to have an inverse function. To find one algebraically: replace `f(x)` with `y`, interchange `x` and `y`, solve for `y`, then rename `y` as `f⁻¹(x)`.

Check inverses by showing that `f(f⁻¹(x)) = x` on the appropriate domain.

## Composition

`(f ∘ g)(x)` means `f(g(x))`: apply `g` first, then use that result as the input for `f`. The order matters.

If `f(x) = 2x + 1` and `g(x) = x²`, then `(f ∘ g)(x) = 2x² + 1`, while `(g ∘ f)(x) = (2x + 1)²`.

## Common mistakes

- Treating a horizontal scale factor exactly like a vertical one.
- Forgetting to restrict a quadratic's domain before claiming its inverse is a function.
- Applying functions in the wrong order in a composition.

## Guided practice

1. State the vertex and direction of opening for `h(x) = 3(x + 2)² - 4`.
2. Explain why `x²` needs a restricted domain before its inverse is a function.
3. Let `p(x) = x - 4` and `q(x) = 3x`. Find `(p ∘ q)(2)`.

## Answer key

1. Vertex `(-2, -4)`; it opens upward.
2. Two different inputs can produce the same output, so the inverse would otherwise assign two outputs to one input.
3. `q(2) = 6`, then `p(6) = 2`.

## Further resources

Use your teacher's course materials for the exact order and emphasis of your class. This lesson is original StudySpring content and is licensed CC BY 4.0.
