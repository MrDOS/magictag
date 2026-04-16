.. This document is written
   using Semantic Linefeeds.
   See http://rhodesmill.org/brandon/2012/one-sentence-per-line/
   for an explanation
   of why linebreaks are
   the way they are.)

========
Magictag
========

Introduction
============

This tool attempts to magically retag your FLAC files.
Sometimes the magic is good.
Sometimes it isn't.
YMMV.

Among other things, it:

* Fixes tag capitalization
  (with the ``--fix-title-case`` flag).
* Moves featured artists from the title tag to the artist tag.
  (Looks for “feat.”/“ft.” by default,
  but also handles “with” with the ``--with-as-feature-term`` flag –
  see below.)
* Adds artist and album sort tags
  (e.g., strips “The” prefixes,
  replaces “style characters” like “$” with their sortable equivalents).
* Adds total track/disc number/total disc tags.
* Adds ReplayGain
  (with the ``--add-replay-gain`` flag;
  shells out to ``metaflac``, so make sure that's installed.)
* Reorders tags and adds a fixed 8K metadata padding
  (to make the output deterministic).
* Renames files to be consistent with their tags.
* Renames the directory to be consistent with the tags of the contained files.
* Sets the ``mtime`` of files and the directory
  to the rip timestamp found in a EAC/XLD/info.txt log file,
  if present.
* Fetches high-resolution album artwork from iTunes.
* Renames album artwork to ``folder.jpg``.

All of these things happen on every invocation.
Due to the lack of customizability,
this isn't a general-purpose tagging tool.
Think of it like a formatting tool
you can run on newly-acquired files
to ensure a consistent baseline
before doing manual tagging,
and then again afterwards
to ensure consistent tag layout.

Feature terms
-------------

Artist features on tracks
are very often indicated with a TITLE tag suffix
rather than an appropriate ARTIST tag.
E.g., “Backseat” by Charli XCX featuring Carly Rae Jepsen might be tagged::

  ARTIST=Charli XCX
  TITLE=Backseat (ft. Carly Rae Jepsen)

Magictag prefers::

  ALBUMARTIST=Charli XCX
  ARTIST=Charli XCX feat. Carly Rae Jepsen
  TITLE=Backseat

To accomplish this,
it searches track TITLEs
for potentially-parenthetical instances
of “feat.” and “ft.” –
“feature terms” –
and, if found, appends the trailing text to the ARTIST.
(There is also a very gross special case for “(featuring”.)

Sometimes, “with” is used as a feature term,
usually when the artists involved
have collaborated much more closely on the songwriting process
(e.g., “Demons” by Fatboy Slim with Macy Gray).
When passed the ``--with-as-feature-term`` flag,
Magictag will treat “with” as a feature term, too.
Mostly, this just causes errors,
because the additional term is handled the same way as the others,
and so it turns “Rock with You” by Michael Jackson
into “Rock” by Michael Jackson with You.
Very occasionally, though,
you'll encounter an album with a lot of tracks “with” another artist
(e.g., all 12 tracks on “Don't Get Too Close” by Skrillex),
and then it can be helpful.

Status
======

Commit history has been slow for the last few years
not because I've lost interest in the project
but because it does basically everything I need it to.
I do use this tool regularly,
typically multiple times a week
(every time I add a new album to my library).
There are a few things I wish it did
or did differently.
Most significantly,
I wish it built a work queue of proposed mutations
so the user could preview and atomically approve/reject them
rather than just blazing ahead and always doing everything.
