CONTROL AUTOMATON SMGCPADEREF
INITIAL STATE Init;
STATE USEFIRST Init :
  CHECK(SMGCPA, "has-invalid-writes") -> ERROR("valid-deref: invalid pointer dereference in $location");
  CHECK(SMGCPA, "has-invalid-reads") -> ERROR("valid-deref: invalid pointer dereference in $location");
END AUTOMATON

CONTROL AUTOMATON SMGCPAFREE
INITIAL STATE Init;
STATE USEFIRST Init :
  CHECK(SMGCPA, "has-invalid-frees") -> ERROR("valid-free: invalid pointer free in $location");
END AUTOMATON

CONTROL AUTOMATON SMGCPAMEMTRACK
INITIAL STATE Init;
STATE USEFIRST Init :
  CHECK(SMGCPA, "has-leaks") -> ERROR("valid-memtrack");
END AUTOMATON
