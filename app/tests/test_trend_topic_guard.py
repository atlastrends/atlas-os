from app.workers.loop_worker import Engine


def test_rejects_ambiguous_viral_game_title():
    engine = Engine.__new__(Engine)

    assert engine._is_ambiguous_source_topic(
        "I shouldn't be allowed to play this game..."
    )


def test_accepts_specific_game_topic():
    engine = Engine.__new__(Engine)

    assert not engine._is_ambiguous_source_topic(
        "O VAZAMENTO do GTA VI"
    )
