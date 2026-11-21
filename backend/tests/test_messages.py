"""Drafted text from recall wording: what the analyst reads as a ticket's headline and in the owner reply."""
from app.workspace.messages import plain_defect, sentences

TESLA = ("Tesla, Inc. (Tesla) is recalling certain 2017-2021 Model S, Model 3, Model X, and 2020-2021 Model Y vehicles "
         "operating software version 2021.36.5.2.  A communication error may cause false forward-collision warning "
         "(FCW) or unexpected activation of the automatic emergency brake (AEB) system.")


def test_no_sentence_break_after_an_abbreviation_but_one_after_a_version_number():
    assert len(sentences(TESLA)) == 2                          # not split after "Inc.", split after "2021.36.5.2."
    assert len(sentences("U.S. Drive Right is recalling certain vehicles. The seat may move.")) == 2


def test_the_headline_names_the_failure_not_the_manufacturer():
    # regression: the ticket headline read "Matches recall 21V-846: Tesla, Inc"
    assert plain_defect(TESLA).startswith("A communication error may cause false forward-collision warning")
