from anki.utils import stripHTMLMedia, intTime, ids2str
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, chooseList, showText, getSaveFile, getFile
from itertools import chain
import json
import re
import sys
import time

MAX_RETRIES = 6


def exportDeck():
    deckId = chooseDeck(prompt="Choose deck to export scheduling from")
    if deckId == 0:
        return
    cids = mw.col.decks.cids(deckId, children=False)
    cards = {}

    for cid in cids:
        card = mw.col.getCard(cid)
        note = mw.col.getNote(card.nid)
        sfld = stripHTMLMedia(
            note.fields[note.col.models.sortIdx(note._model)])
        # Skip new cards
        if card.queue == 0:
            continue
        if sfld in cards:
            showText("Card with duplicated field found; aborting.")
            return

        revlogKeys = ["id", "ease", "ivl", "lastIvl", "factor", "time", "type"]
        revlogsArray = mw.col.db.all(
            "select " +
            ", ".join(revlogKeys) +
            " from revlog " +
            "where cid = ?",
            cid
        )
        revlogsDict = list(map(
            lambda row:
            {revlogKeys[i]: row[i]
                for i in range(0, len(revlogKeys))}, revlogsArray
        ))

        cards[sfld] = dict(
            due=card.due,
            queue=card.queue,
            ivl=card.ivl,
            factor=card.factor,
            left=card.left,
            type=card.type,
            lapses=card.lapses,
            reps=card.reps,
            flags=card.flags,
            revlogs=revlogsDict
        )

    file = getSaveFile(
        mw,
        "Export scheduling info to file",
        "anki-times",
        "JSON",
        ".json",
        re.sub('[\\\\/?<>:*|"^]', '_',
               mw.col.decks.name(deckId)) + "-scheduling"
    )
    if not file:
        return

    output = {
        "meta": {
            "crt": mw.col.crt
        },
        "cards": cards
    }

    with open(file, "w") as f:
        json.dump(output, f, ensure_ascii=False)


def importDeck():
    mw.checkpoint("Import scheduling info")
    try:
        _importDeck()
    except:
        mw.col.db.rollback()
        raise


def _importDeck():
    logs = []
    now = intTime()
    importedN = 0

    deckId = chooseDeck(prompt="Choose deck to import scheduling into")
    if deckId == 0:
        return
    file = getFile(mw, "", None, filter="*.json", key="anki-times")
    if not file:
        return

    data = {}
    with open(file, "r") as f:
        data = json.load(f)

    crt = data["meta"]["crt"]
    cards = data["cards"]

    for key in cards:
        src = cards[key]
        destCids = mw.col.db.list(
            "select distinct(c.id) from cards as c, notes as n "
            "where c.nid=n.id and c.did=? and n.sfld=?",
            deckId,
            key
        )

        # If there are no destination cards, skip
        if not destCids:
            continue
        if len(destCids) > 1:
            logs.append(
                f"Multiple destination cards not supported. Matched field={key}")
            continue
        logs.append(f"Matched card {key}")

        destCid, = destCids

        mw.col.db.execute(
            "update cards set "
            "due=:due, mod=:now, usn=:usn, queue=:queue, lapses=:lapses, "
            "reps=:reps, flags=:flags, "
            "ivl=:ivl, factor=:factor, left=:left, type=:type "
            "where id=:cid",
            cid=destCid,
            now=now,
            usn=mw.col.usn(),
            **src
        )

        for i in range(0, MAX_RETRIES + 1):
            try:
                if i == 0:
                    importRevlogs(0, destCid, src["revlogs"])
                else:
                    importRevlogs(1 << (i - 1), destCid, src["revlogs"])
                break
            except:
                if i == MAX_RETRIES:
                    raise
        importedN += 1

    logs.append(f"Copied {importedN} cards")

    showText("\n".join(logs), title="Import scheduling info log")
    mw.reset()


def importRevlogs(offset, cid, revlogs):
    mw.col.db.executemany(
        "insert into revlog " +
        "values(:id + :offset, :cid, :usn,"
        ":ease, :ivl, :lastIvl, :factor, :time, :type)",
        map(
            lambda revlog: dict(offset=offset, cid=cid,
                                usn=mw.col.usn(), **revlog),
            revlogs
        )
    )


def chooseDeck(prompt="Choose deck"):
    "Shows a deck selector and returns the deck ID. If cancelled, return 0."
    choices = sorted(mw.col.decks.allNames())
    chosenIndex = chooseList(prompt, ["Cancel"] + choices)
    if chosenIndex == 0:
        return 0

    return mw.col.decks.id(choices[chosenIndex - 1])


def createAction(label, fn, target=mw.form.menuTools):
    action = QAction(label, mw)
    action.triggered.connect(fn)
    target.addAction(action)


createAction("Export scheduling info...", exportDeck)
createAction("Import scheduling info...", importDeck)
