from webssh.history import OutputHistory


def test_history_keeps_absolute_sequence_after_trimming() -> None:
    history = OutputHistory(max_bytes=5)

    first = history.append(b"abc")
    second = history.append(b"def")

    assert first.seq == 0
    assert second.seq == 3
    assert history.next_seq == 6
    assert history.earliest_seq == 3
    assert [chunk.data for chunk in history.since()] == [b"def"]


def test_history_since_returns_overlapping_chunk() -> None:
    history = OutputHistory(max_bytes=100)
    history.append(b"abc")
    history.append(b"def")

    chunks = history.since(4)

    assert len(chunks) == 1
    assert chunks[0].seq == 4
    assert chunks[0].data == b"ef"
