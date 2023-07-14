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
  but also handles “with” with the ``--with-as-feature-term`` flag.)
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
* Fetches high-resolution album artwork from iTunes
  (if python-itunes_ is installed –
  it isn't installed by ``./setup.py install``,
  because the version on PyPI
  does not support Python 3).
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

.. _python-itunes: https://github.com/talolard/python-itunes

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
