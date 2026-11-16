# Task: `parse_inr`

Write `parse_inr(text: str) -> int` in `money.py`. It reads an Indian rupee
amount the way a person would type it and returns the amount in **paise**
(100 paise = 1 rupee).

## Accepted input

1. Leading and trailing whitespace does not matter.
2. A currency marker is optional. If present it comes **before** the number and
   is one of `₹`, `Rs`, `Rs.` or `INR`, in any letter case, with or without a
   space after it.
3. Commas between digits are ignored, whatever the grouping: `1,25,000`,
   `125,000` and `1,2,5000` all mean 125000 rupees.
4. A decimal part is allowed. With no suffix (rule 5), at most two digits may
   follow the point: `12.5` and `12.50` are fine, `12.345` is not.
5. An optional suffix scales the number. It may be separated from the number by
   spaces or not, and is case-insensitive:

   | Suffix | Multiplier |
   |---|---|
   | `k` | 1,000 |
   | `l`, `lakh`, `lakhs` | 1,00,000 |
   | `cr`, `crore`, `crores` | 1,00,00,000 |

   With a suffix, any number of decimal digits is allowed, as long as the final
   amount is a whole number of paise (`1.2345 lakh` is fine).
6. A negative amount has a single leading `-`, or the whole amount is wrapped in
   parentheses: `-₹200` and `(₹200)` both mean minus 200 rupees.

## Output

The exact amount in paise, as an `int`. Floating-point rounding must never
change the answer.

## Everything else is an error

Raise `ValueError` for anything the rules above don't allow, for example: an
empty string, no digits, a marker or suffix with no number, more than one
decimal point, scientific notation, an unknown word, a marker after the number,
or an amount that is not a whole number of paise.
