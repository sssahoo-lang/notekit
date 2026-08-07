"""diagram_claims turns Mermaid source into checkable sentences, so a
diagram's edges get scored for faithfulness the same as prose. It is
deterministic on purpose -- no model call -- which is exactly what makes it
worth pinning down with tests: a regex change here silently changes what
"faithfulness" measures."""

from notekit.evaluation import diagram_claims

FLOWCHART = """Some notes before.

```mermaid
flowchart LR
    A[State] --> B[Action]
    B --> C[Reward]
```
Caption: the loop [c12]."""


def test_extracts_one_claim_per_labelled_edge():
    claims = diagram_claims(FLOWCHART)
    assert claims == ["State leads to Action.", "Action leads to Reward."]


def test_no_diagram_returns_no_claims():
    assert diagram_claims("Plain prose with no fenced code at all.") == []
    assert diagram_claims("") == []


def test_edge_label_becomes_the_relation_phrase():
    body = """```mermaid
flowchart LR
    A[Agent] -->|selects| B[Action]
```"""
    assert diagram_claims(body) == ["Agent selects Action."]


def test_node_label_is_remembered_across_edges():
    # Only the first edge that introduces a node carries its label; the
    # second edge referencing the same id by itself should still resolve to
    # the label, not fall back to the bare identifier.
    body = """```mermaid
flowchart LR
    A[State] --> B[Action]
    B --> C
```"""
    claims = diagram_claims(body)
    assert claims == ["State leads to Action.", "Action leads to C."]


def test_unlabelled_nodes_fall_back_to_their_bare_id():
    body = """```mermaid
flowchart LR
    A --> B
```"""
    assert diagram_claims(body) == ["A leads to B."]


def test_sequence_diagram_messages_are_extracted():
    body = """```mermaid
sequenceDiagram
    Agent->>Environment: selects action
    Environment->>Agent: returns reward
```"""
    claims = diagram_claims(body)
    assert claims == [
        "Agent → Environment: selects action.",
        "Environment → Agent: returns reward.",
    ]


def test_comment_lines_are_ignored():
    body = """```mermaid
flowchart LR
    %% this is just a note for the diagram author
    A[State] --> B[Action]
```"""
    assert diagram_claims(body) == ["State leads to Action."]


def test_multiple_diagram_blocks_are_all_scored():
    body = """```mermaid
flowchart LR
    A[State] --> B[Action]
```
Some prose in between.
```mermaid
flowchart LR
    C[Policy] --> D[Value]
```"""
    claims = diagram_claims(body)
    assert claims == ["State leads to Action.", "Policy leads to Value."]


def test_non_diagram_code_fences_are_ignored():
    body = """```python
def f(a, b):
    return a --> b
```"""
    assert diagram_claims(body) == []


def test_round_and_diamond_node_shapes_are_handled():
    body = """```mermaid
flowchart LR
    A(Round start) --> B{Decision point}
```"""
    assert diagram_claims(body) == ["Round start leads to Decision point."]
