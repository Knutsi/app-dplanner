import sys
from datetime import date, datetime
from pathlib import Path
from dplanner.domain.store import LibraryStore
from dplanner.planning.schedule import status_on
from dplanner.planning.status import read_since, stored
from dplanner.planning.kinds import key_of
lib = LibraryStore(Path(sys.argv[1])).load()
st = status_on(lib, date.today())
for p in lib.projects:
    if p.title != sys.argv[2]: continue
    for s in p.steps:
        print(key_of(s), s.title, "stored", stored(s), "since", read_since(s), "created", s.created, "->", st(s))
