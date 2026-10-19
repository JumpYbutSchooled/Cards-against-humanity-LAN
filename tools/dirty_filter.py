"""Decides whether a card is a sex joke or plain vulgarity (used to build the "Sex & Vulgarity" mix).

A word list rather than anything clever: CAH cards are short and blunt, so this catches the
vast majority. It deliberately ignores drugs, politics and violence - only sex and crudeness.
"""
import re

_TERMS = r"""
sex|sexy|sexual\w*|sexting|sexts?|kama\s?sutra|orgasm\w*|foreplay|horny|aroused|arousal|erotic\w*|seduc\w*
|naked|nude\w*|nudity|nudes|strip(?:per|pers|ping|tease|\s?club)|lap\s?dance\w*|pole\s?danc\w*|lingerie|panties|thong
|porn\w*|onlyfans|pornhub|xxx|milf|dilf|thots?|cuck\w*|threesome\w*|foursome|orgy|orgies|gang\s?bang\w*|swinger\w*
|bukkake|creampie|money\s?shot|golden\s?shower\w*|glory\s?hole\w*|teabag\w*|motorboat\w*|pegging|fisting|fingering
|finger\s?bang\w*|rim\s?job\w*|blow\s?jobs?|hand\s?jobs?|foot\s?jobs?|tit\s?jobs?|69|sixty-nine|doggy\s?style|missionary
|reverse\s?cowgirl|scissoring|queef\w*|spank\w*|bdsm|bondage|dominatrix|kink\w*|fetish\w*|gimp|ball\s?gag\w*
|dildo\w*|vibrator\w*|butt\s?plugs?|sex\s?toys?|fleshlight\w*|condoms?|lube|viagra|erectile|erections?|boners?
|morning\s?wood|blue\s?balls|masturbat\w*|jerk(?:s|ed|ing)?\s?(?:it\s)?off|jack(?:s|ed|ing)?\s?off|beat(?:s|ing)?\s?off
|rub(?:s|bing)?\s?one\s?out|wank\w*|fap\w*|cum|cums|cumming|cummed|cumshot\w*|jizz\w*|spunk|semen|sperm\w*|ejaculat\w*
|penis\w*|peni|cocks?|cockblock\w*|dicks?|dickhead\w*|dicking|schlong\w*|wang|wangs|dongs?|wiener\w*|weiner\w*|pecker\w*
|testic\w*|scrotum\w*|ballsack\w*|nutsack\w*|balls|vagina\w*|vulva\w*|labia\w*|clit\w*|pussy|pussies|cunt\w*|twat\w*
|coochie\w*|cooch|vajayjay|snatch|poon\w*|camel\s?toe\w*|beaver\s?shot|muff\w*|pubic|pubes?|genital\w*|crotch\w*|groin\w*
|tits|titty|titties|boob\w*|breasts?|nipple\w*|knockers|areola\w*|butt|butts|butthole\w*|buttcheek\w*|booty|ass|asses
|asshole\w*|anal|anus|anuses|rectum\w*|rectal|prostate|sphincter\w*|virgin|virgins|virginity|std|stds|herpes|chlamydia
|gonorrhea|syphilis|crabs|hump\w*|horndog\w*|nympho\w*|whore\w*|slut\w*|skank\w*|hooker\w*|prostitut\w*|escort\w*
|brothel\w*|pimp\w*|sugar\s?daddy|fuck\w*|motherfuck\w*|shit\w*|bullshit|bitch\w*|bastard\w*|douche\w*|piss\w*
|fart\w*|poop\w*|turds?|diarrhea|diarrhoea|smegma|feces|faeces|dookie|shart\w*|taint|boogers?
"""
_PATTERN = re.compile(r"(?<![\w-])(?:" + "".join(_TERMS.split()) + r")(?![\w-])", re.IGNORECASE)
# Names and phrases that look dirty but aren't.
_FALSE = re.compile(r"moby\s+dick|dick\s+(?:cheney|van\s+dyke|clark|butkus|tracy|grayson|wolf)|philip\s+k\.?\s+dick|"
                    r"tricky\s+dick|dick\s+and\s+jane|ass(?:es)?\s+(?:and|or)\s+(?:mule|donkey)|jackass|kick\s+ass|"
                    r"bad\s*ass|cum\s+laude|virgin\s+(?:mary|islands|atlantic|galactic|records|mobile)|"
                    r"crabs?\s+adjust|cocktail|muffin|hump\s*day|camel\s+hump|breasts?\s+cancer", re.IGNORECASE)


def is_dirty(text):
    t = _FALSE.sub(" ", text.replace("\n", " "))
    return bool(_PATTERN.search(t))
