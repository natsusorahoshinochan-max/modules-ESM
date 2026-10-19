# Public example formats

`example.note`: `entry` names a UTF-8 text file. Its logical key is arbitrary. Other files may carry producer-owned metadata; readers can ignore them. The text file alone contains all content needed to uppercase or count a note. `sample/note.txt` is a valid entry. No scientific schema, generator installation, or history is required to read it.

`example.count`: `entry` names a UTF-8 file containing the decimal number of Unicode characters in the input note. `sample/count.txt` is a valid entry.

The independent receiver only imports the public author SDK and implements the note contract directly.
