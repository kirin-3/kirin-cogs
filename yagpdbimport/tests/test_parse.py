from yagpdbimport.yagpdbimport import parse_yagpdb_warnings

RAW = r"""[
 {"ID":9631664,"CreatedAt":"2020-07-01T20:14:34.01748Z","GuildID":684360255798509578,"UserID":140186220255903746,
  "AuthorID":"204255221017214977","AuthorUsernameDiscrim":"YAGPDB.xyz#8760","Message":"Automoderator:\nSpamming is not allowed.","LogsLink":""},
 {"ID":9631663,"CreatedAt":"2020-07-01T20:14:33.675467Z","GuildID":684360255798509578,"UserID":140186220255903746,
  "AuthorID":"204255221017214977","AuthorUsernameDiscrim":"YAGPDB.xyz#8760","Message":"older","LogsLink":""},
 {"ID":1,"CreatedAt":"2020-07-01T20:14:34Z","GuildID":1,"UserID":2,"AuthorID":"3","AuthorUsernameDiscrim":"x","Message":"other guild","LogsLink":""}
]"""


def test_parse_maps_filters_and_orders() -> None:
    rows = parse_yagpdb_warnings(RAW, 684360255798509578, points=1)
    assert len(rows) == 2  # other guild dropped
    (user_id, key, warning), (_, older_key, _) = rows
    assert user_id == 140186220255903746
    assert warning == {
        "points": 1,
        "description": "Automoderator:\nSpamming is not allowed. (YAGPDB, 2020-07-01, by YAGPDB.xyz#8760)",
        "mod": 204255221017214977,
    }
    assert int(older_key) < int(key)  # keys sort by date
    assert parse_yagpdb_warnings(RAW, 684360255798509578, points=1)[0][1] == key  # stable, so re-import dedupes
