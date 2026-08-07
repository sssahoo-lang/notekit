"""parse_quiz reads a fixed plain-text layout rather than requesting structured
output, because structured output changes the request prefix and breaks
prompt-cache reuse with the notes call (see the README's engineering notes —
this was a real $0.658 -> $0.339 fix). The parser has to be strict: `None`
signals "fall back to the structured-output path", so a false positive here
is worse than a false negative."""

from notekit.pipeline import parse_quiz

ONE_QUESTION = """Q: What does Q-learning estimate?
A) The optimal policy directly
B) The action-value function
C) The state transition model
D) The reward function
ANSWER: B
WHY: The passages define Q-learning as estimating action-values [c12]."""

TWO_QUESTIONS = (
    ONE_QUESTION
    + "\n\n"
    + """Q: What is the Bellman optimality equation used for?
A) Normalizing rewards
B) Defining the optimal value function recursively
C) Selecting the discount factor
D) Initializing the Q-table
ANSWER: B
WHY: Passages describe Bellman optimality as the recursive definition [c44]."""
)


def test_parses_a_single_question():
    quiz = parse_quiz(ONE_QUESTION)
    assert quiz is not None
    assert len(quiz.questions) == 1
    q = quiz.questions[0]
    assert q.question == "What does Q-learning estimate?"
    assert q.options == [
        "The optimal policy directly",
        "The action-value function",
        "The state transition model",
        "The reward function",
    ]
    assert q.answer_index == 1  # B
    assert "action-values" in q.explanation


def test_parses_multiple_questions_separated_by_a_blank_line():
    quiz = parse_quiz(TWO_QUESTIONS)
    assert quiz is not None
    assert len(quiz.questions) == 2
    assert quiz.questions[1].answer_index == 1


def test_answer_letter_maps_to_the_right_zero_based_index():
    for letter, index in [("A", 0), ("B", 1), ("C", 2), ("D", 3)]:
        text = ONE_QUESTION.replace("ANSWER: B", f"ANSWER: {letter}")
        quiz = parse_quiz(text)
        assert quiz.questions[0].answer_index == index


def test_answer_letter_is_case_insensitive():
    text = ONE_QUESTION.replace("ANSWER: B", "ANSWER: b")
    quiz = parse_quiz(text)
    assert quiz.questions[0].answer_index == 1


def test_why_is_optional():
    text = ONE_QUESTION.split("\nWHY:")[0]
    quiz = parse_quiz(text)
    assert quiz is not None
    assert quiz.questions[0].explanation == ""


def test_missing_option_fails_the_whole_parse():
    # A block with an empty option is exactly the kind of malformed output the
    # structured-output fallback exists for — returning a partial quiz would
    # be worse than falling back.
    broken = ONE_QUESTION.replace("B) The action-value function", "B)")
    assert parse_quiz(broken) is None


def test_missing_answer_line_fails_to_parse():
    broken = ONE_QUESTION.replace("ANSWER: B\n", "")
    assert parse_quiz(broken) is None


def test_empty_text_returns_none_not_an_empty_quiz():
    assert parse_quiz("") is None
    assert parse_quiz("The model refused to write questions.") is None


def test_surrounding_prose_does_not_break_extraction():
    # Models sometimes ignore "nothing else" and add a lead-in sentence;
    # the parser should still find the well-formed block.
    text = "Here are the questions:\n\n" + ONE_QUESTION
    quiz = parse_quiz(text)
    assert quiz is not None
    assert len(quiz.questions) == 1


def test_extra_whitespace_between_lines_is_tolerated():
    loose = ONE_QUESTION.replace("\n", "\n  ")
    quiz = parse_quiz(loose)
    assert quiz is not None
    assert quiz.questions[0].answer_index == 1
