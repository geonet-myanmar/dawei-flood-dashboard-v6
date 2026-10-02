"""
Hand-encode the 88 Dawei Watch posts of 26 Sep - 2 Oct 2026 into structured data and
geocode every named place against MIMU.

Source: Dawei Watch Facebook page (https://web.facebook.com/DaweiWatch), posts
collected by the user into dawei_flood.docx, newest first. Copied to
data/source/dawei_watch_2026-09-26_10-02.txt with one paragraph per line; every
`line` below is a line number in that file, so each figure traces back to the text.
The post a line belongs to is worked out from the file itself (each post starts
with a headline followed by a "Dawei Watch | <date>" line).

Model
  SITES      one record per place. `reports` lists what each post said about it,
             in the order written; the post fixes the day. A site's state on a day
             (severity, figures, red-level flag, rescue access) is built from the
             reports published up to that day, so the map can step 26 -> 27 -> 28 -> 29 -> 30 Sep -> 1 -> 2 Oct.
             Days are numbered on from September, so 1 Oct is day 31 and 2 Oct day 32.
  INCIDENTS  roads, bridges and slides that are not villages, also dated.
  RESCUE     the rescue convoy's progress south into Launglon.
  TIMELINE   events by the time they happened (not when they were posted).
  QUOTES     residents and responders, Myanmar original plus a close translation.

Severity of a report (ordinal) -- what happened to people there
  fatal     deaths or missing people reported
  severe    houses buried or submerged to the roof, people trapped, a whole
            village under water, or a red-level designation
  affected  named as flooded or hit by landslides, no further detail
A site's severity on a day is the highest of its reports so far: later reports add
detail, they do not make an earlier disaster smaller.

Geocoding grades (`match`), by Myanmar-script name (VLG_MMR) within the township:
  exact     MIMU has the name as written
  variant   MIMU spells it differently or files it under the next township
  probable  best candidate, not certain
  approx    not in MIMU; placed at a stated reference
  unlocated not in MIMU and no defensible position; listed, not mapped
"""

import bisect
import json
import os
import re
import warnings

import geopandas as gpd
from shapely.geometry import Point

warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")

HERE = os.path.dirname(__file__)
RAW = os.path.join(HERE, "..", "data", "raw")
SRC = os.path.join(HERE, "..", "data", "source", "dawei_watch_2026-09-26_10-02.txt")
OUT = os.path.join(HERE, "..", "data", "processed", "flood.json")
DAYS = [26, 27, 28, 29, 30, 31, 32]  # 31 = 1 Oct, 32 = 2 Oct

# ---------------------------------------------------------------------------
# Posts, oldest first. `h` is the headline's line number; `as_of` is the latest
# time the post's own text refers to.
# ---------------------------------------------------------------------------
POSTS = [
    dict(h=1172, day=26, as_of="26 Sep, 6 pm", kind="Breaking news",
         en="Landslide at Kyauk Ni Maw, Launglon, buries people and houses; emergency rescue needed"),
    dict(h=1154, day=26, as_of="26 Sep, night",
         en="Floods and landslides in Launglon; families move out overnight"),
    dict(h=1142, day=27, as_of="27 Sep, 9:30 am",
         en="Floods and landslides in Launglon Township; emergency help needed"),
    dict(h=1111, day=27, as_of="27 Sep, morning", kind="Round-up",
         en="Floods and landslides in Dawei District, township by township"),
    dict(h=1089, day=27, as_of="27 Sep, late morning",
         en="About 20 villages flooded in Launglon, hills collapse, at least two missing including a child"),
    dict(h=1082, day=27, as_of="27 Sep, midday",
         en="Kadet Nge [Htein] landslide: about 10 missing, bodies of a child and a woman found"),
    dict(h=1076, day=27, as_of="27 Sep, midday",
         en="Min Yat landslide buries mother and child; mother dies, rescuers still working to free the child"),
    dict(h=1063, day=27, as_of="27 Sep",
         en="Flooded Thayetchaung Township needs emergency rescue"),
    dict(h=1052, day=27, as_of="27 Sep, 12 noon",
         en="Landslides continue on Launglon's western hills"),
    dict(h=1043, day=27, as_of="27 Sep",
         en="Landslide at Kayin Gyi, Launglon, buries nearly 30 houses"),
    dict(h=1033, day=27, as_of="27 Sep",
         en="Today's rain at Dawei sets an all-time record"),
    dict(h=1024, day=27, as_of="27 Sep, 3:30 pm",
         en="Floods on the Dawei–Myeik road: some vehicles turn back, others stranded"),
    dict(h=971, day=27, as_of="27 Sep, 2:30 pm", kind="Round-up",
         en="Floods and landslides bring a sea of suffering to the Dawei region"),
    dict(h=958, day=27, as_of="27 Sep, 4:30 pm",
         en="More landslides near Launglon; search-and-rescue teams cannot advance"),
    dict(h=942, day=27, as_of="27 Sep",
         en="Dozens of villages flooded in Thayetchaung; buffalo and cattle killed"),
    dict(h=931, day=27, as_of="27 Sep, evening",
         en="Streams overflow across Dawei town; power cut to the whole town"),
    dict(h=918, day=28, as_of="28 Sep, morning",
         en="Single-storey houses under water in Dawei town wards"),
    dict(h=904, day=28, as_of="28 Sep",
         en="Thayetchaung needs emergency help"),
    dict(h=868, day=28, as_of="27 Sep, late", kind="Explainer",
         en="Record Dawei rain and a sudden disaster",
         note="Dated 27 Sep in its text; posted among the 28 Sep updates."),
    dict(h=857, day=28, as_of="28 Sep",
         en="Whole village of Pa Kar Ri on the Dawei–Htee Khee road under water; low houses submerged"),
    dict(h=845, day=28, as_of="28 Sep, morning",
         en="Another landslide at Kayin Gyi, Launglon; the east side of the village destroyed"),
    dict(h=835, day=28, as_of="28 Sep",
         en="Tanintharyi River and streams rise; villages begin to flood"),
    dict(h=823, day=28, as_of="28 Sep, 12 noon",
         en="Advance rescue team reaches Kadet Nge Htein, where dozens are missing; search begins"),
    dict(h=815, day=28, as_of="28 Sep, morning",
         en="Landslide at Nyaw Pyin, Launglon, kills two women"),
    # ---- added with the 29 Sep update: later 28 Sep posts, then 29 Sep
    dict(h=800, day=28, as_of="28 Sep, evening",
         en="Water falls in Launglon town and some villages; seven cattle swept away at Way Di saved"),
    dict(h=793, day=28, as_of="28 Sep",
         en="Landslides at Pa Nyit, Launglon, cut off villages beyond it"),
    dict(h=781, day=28, as_of="28 Sep, evening",
         en="Dawei sets another rainfall record today"),
    dict(h=724, day=28, as_of="28 Sep, evening", kind="Feature",
         en="What Thayetchaung is going through"),
    dict(h=715, day=28, as_of="28 Sep, evening",
         en="Landslide kills a mother and son at Ka Det Gyi, Launglon"),
    dict(h=703, day=28, as_of="28 Sep, evening",
         en="More than 600 flood victims in Dawei town need food, clothes and medicine"),
    dict(h=691, day=28, as_of="28 Sep, evening",
         en="Three more bodies found at Kadet Nge Htein; five dead there"),
    dict(h=619, day=28, as_of="28 Sep, afternoon", kind="Explainer",
         en="Help falls short and rescuers can't get through in the Dawei disaster zone"),
    dict(h=616, day=28, as_of="28 Sep", kind="Video",
         en="Advance rescue team reaches Kadet Nge Htein, where dozens are missing"),
    dict(h=608, day=28, as_of="28 Sep, evening",
         en="River rises into Lay Hnya village, Bokpyin: roads and houses begin to flood"),
    dict(h=577, day=28, as_of="28 Sep", kind="Interview",
         en="The people standing up to the Dawei flood and landslide disaster"),
    dict(h=565, day=28, as_of="28 Sep, evening",
         en="Thayetchaung flood deaths reach six; two more swept away"),
    dict(h=556, day=28, as_of="28 Sep, night",
         en="Kyauk Ni Maw landslide buries about 50 houses; at least five missing"),
    dict(h=547, day=29, as_of="29 Sep, morning",
         en="Mother and son still missing at Tha Byar, Launglon"),
    dict(h=539, day=29, as_of="29 Sep, midday", kind="Photo story",
         en="Water recedes in Dawei town"),
    dict(h=522, day=29, as_of="28 Sep, night", kind="Interview",
         en="Nyaw Pyin, knocked down again and again, needs help to get back up",
         note="Interview recorded on the night of 28 Sep; posted on 29 Sep."),
    dict(h=512, day=29, as_of="29 Sep",
         en="Inwa hill slide at Thea Pon, Launglon, wrecks a monastery and orchards"),
    dict(h=502, day=29, as_of="29 Sep",
         en="Tanintharyi River keeps rising: residents move out as 20+ villages go under"),
    dict(h=488, day=29, as_of="29 Sep, midday", kind="Round-up",
         en="Disaster deaths in the Dawei region pass 20"),
    dict(h=478, day=29, as_of="29 Sep, 3 pm",
         en="Tanintharyi River passes 26 ft, above its danger mark"),
    dict(h=466, day=29, as_of="29 Sep",
         en="Water falls in Thayetchaung, but power cuts keep phones down"),
    dict(h=448, day=29, as_of="29 Sep", kind="Interview",
         en="Kyauk Ni Maw, still cut off among the slides and the wreckage"),
    dict(h=438, day=29, as_of="29 Sep",
         en="Ti Zit, trapped by landslides, needs food"),
    dict(h=435, day=29, as_of="29 Sep", kind="Video",
         en="Water falls in Thayetchaung; power cut makes contact hard"),
    dict(h=432, day=29, as_of="29 Sep", kind="Video",
         en="Mother and son still missing at Tha Byar, a Launglon landslide village"),
    # ---- added with the 30 Sep update: later 29 Sep posts, then 30 Sep
    dict(h=377, day=29, as_of="29 Sep, afternoon", kind="Round-up",
         en="Deaths and missing still rising, people still cut off: the Dawei disaster"),
    dict(h=366, day=29, as_of="29 Sep, evening",
         en="Rescue teams from Mon State, Kayin State and Myeik reach Dawei; a Mandalay team to follow"),
    dict(h=356, day=29, as_of="29 Sep",
         en="Hill stream washes out the road at the Kayin Gyi bridge, Launglon"),
    dict(h=350, day=29, as_of="29 Sep, evening", kind="Photo story",
         en="Dawei town this evening, after the water fell",
         note="Byline dated 30 Sep; its text describes the evening of 29 Sep."),
    dict(h=343, day=29, as_of="29 Sep",
         en="Tha Byar bridge, Launglon, undermined and dangerous to cross"),
    dict(h=336, day=30, as_of="30 Sep, morning", kind="Photo story",
         en="Pauk Taing bridge on the road out of Dawei, after the water fell"),
    dict(h=327, day=29, as_of="29 Sep, night",
         en="Whole village of Ban Pyae, Tanintharyi, under water; residents move up a hill and need food"),
    dict(h=315, day=30, as_of="30 Sep",
         en="Tanintharyi Region emergency team and partners head for Kayin Gyi, Kan Pa Ni and Tha Byar"),
    dict(h=307, day=30, as_of="30 Sep", kind="Interview",
         en="Unreached and unheard: Kyauk Twin's villagers run short of food"),
    dict(h=301, day=30, as_of="30 Sep, morning",
         en="Tha Byar bridge on the Dawei–Launglon road collapses"),
    dict(h=291, day=29, as_of="29 Sep",
         en="Tha Kyet Taw and at least seven villages beyond it, at the tip of the Launglon peninsula, urgently "
            "need food",
         note="Its text dates the rescue teams' arrival at Tha Win 'today, 31 September', a slip for 29 or 30 Sep."),
    dict(h=280, day=30, as_of="30 Sep",
         en="Tanintharyi River still rising: houses go under in Ta Ku tract"),
    dict(h=269, day=30, as_of="30 Sep",
         en="Kyauk Ni Maw, still cut off, urgently needs drinking water"),
    dict(h=250, day=29, as_of="29 Sep",
         en="Eight dead and 27 houses destroyed in Thayetchaung"),
    dict(h=240, day=30, as_of="30 Sep, 3 pm",
         en="Water falls in Chaung La Mu tract, Tanintharyi: lorries move again, passenger vehicles still stuck"),
    dict(h=229, day=30, as_of="30 Sep",
         en="The broken road at the Kayin Gyi bridge, Launglon, is repaired"),
    dict(h=218, day=30, as_of="30 Sep",
         en="A man killed and 20 houses destroyed at Za Lut Pyin Gyi, Launglon"),
    # ---- added with the 1 Oct update: later 30 Sep posts, then 1 Oct (day 31)
    dict(h=207, day=30, as_of="30 Sep",
         en="Cut off by slides, Launglon villages lose people who could not get treatment in time"),
    dict(h=196, day=30, as_of="30 Sep, evening",
         en="Tanintharyi River more than 5 ft over its danger mark, close to the 2024 record"),
    dict(h=193, day=31, as_of="1 Oct", kind="Video",
         en="At least eight villages at the tip of the Launglon peninsula urgently need food"),
    dict(h=161, day=31, as_of="30 Sep, evening", kind="Explainer",
         en="Tanintharyi, where tens of thousands have begun to move out",
         note="Its text is written on the evening of 30 Sep; posted on 1 Oct."),
    dict(h=151, day=30, as_of="30 Sep",
         en="Dawei association in Korea gives more than 100 lakh kyats for the Launglon disaster"),
    dict(h=145, day=31, as_of="30 Sep", kind="Photo story",
         en="Villagers clear the slides on the Myat Shin Maw road themselves"),
    dict(h=132, day=31, as_of="1 Oct",
         en="Kyauk Ni Maw landslide destroys nearly 100 houses and kills two"),
    dict(h=124, day=31, as_of="1 Oct",
         en="Yangon's Dawei Sangha Union to give more than 300 lakh kyats for the Dawei disaster"),
    dict(h=114, day=31, as_of="1 Oct",
         en="Yay Paw and Tha Mee Hla under water, residents trapped"),
    dict(h=104, day=31, as_of="1 Oct",
         en="Tanintharyi River keeps rising: more people move out in Ta Ku tract"),
    dict(h=97, day=31, as_of="1 Oct",
         en="Another woman's body found at Kadet Nge Htein, Launglon"),
    dict(h=87, day=31, as_of="1 Oct, midday",
         en="No drinking water at Ban Pyae and Myay Ma Ohn, both entirely under water"),
    dict(h=84, day=31, as_of="1 Oct", kind="Video",
         en="Yay Paw and Tha Mee Hla under water, residents trapped"),
    dict(h=81, day=31, as_of="1 Oct", kind="Video",
         en="Kyauk Ni Maw landslide destroys nearly 100 houses and kills two"),
    dict(h=68, day=31, as_of="1 Oct",
         en="Five dead and more than 40 houses destroyed at Taw Kye, Launglon"),
    # ---- added with the 2 Oct update (day 32)
    dict(h=54, day=32, as_of="1 Oct", kind="Round-up",
         en="Disaster deaths in the Dawei region pass 40",
         note="Its figures are those collected up to 1 Oct; posted on 2 Oct."),
    dict(h=47, day=32, as_of="1 Oct",
         en="Bodies of all three family members buried at Tha Byar, Launglon, recovered",
         note="Its text calls 1 Oct 'today'; posted on 2 Oct."),
    dict(h=35, day=32, as_of="2 Oct, morning",
         en="Nearly all of Tanintharyi town under water; thousands of townspeople move out"),
    dict(h=21, day=32, as_of="1 Oct",
         en="No plan yet to restore power to Launglon Township, junta deputy minister says"),
    dict(h=18, day=32, as_of="1 Oct", kind="Video",
         en="Bodies of three family members buried at Tha Byar, Launglon, recovered"),
    dict(h=6, day=32, as_of="2 Oct",
         en="Kyauk Ta Lone tract, under water for over a week, urgently needs drinking water"),
    dict(h=3, day=32, as_of="2 Oct", kind="Video",
         en="Nearly all of Tanintharyi town under water; thousands of townspeople move out"),
]


def R(line, sev, text, **kw):
    return dict(line=line, sev=sev, text=text, **kw)


LIST27 = ("Named among villages hit by floods and landslides between Ka Myaw Gyi, at the "
          "Dawei–Launglon boundary, and Kyauk Ni Maw.")

# ---------------------------------------------------------------------------
# Sites
# roles: relief (camp/shelter) | needs (aid requested) | access (road/bridge cut)
#        | comms (contact lost) | observe (observation only) | school
#        | receding (the water is reported falling)
# rescue: "reached" | "not-reached"
# ---------------------------------------------------------------------------
SITES = [
    # ================================================== Launglon, north of town
    dict(id="ka-myaw-gyi", mm="ကမြောကြီး", en="Ka Myaw Gyi", ts="Launglon", area="Launglon north",
         hazard="both", reports=[
             R(1094, "affected", LIST27),
             R(1106, "affected", "Floods and landslides: vehicles barred from Ka Myaw Gyi onward.", roles=["access"]),
             R(1147, "affected", "Rescue teams heading for southern Launglon were held up by flooding at "
                                "Ka Myaw Gyi on the morning of 27 Sep.", roles=["access"]),
         ]),
    dict(id="inn-wun", mm="အင်းဝန်း", en="Inn Wun", ts="Launglon", area="Launglon north", hazard="flood",
         reports=[
             R(1094, "affected", LIST27),
             R(1104, "affected", "Near the Dawei River; residents say the water is waist-deep.", depth_ft=3),
         ]),
    dict(id="min-yat", mm="မင်းရပ်", en="Min Yat", ts="Launglon", area="Launglon north", hazard="both",
         reports=[
             R(1060, "severe", "Many houses buried by landslides."),
             R(1078, "fatal", "A slide in Min Yat Chaung, west of the village, buried a mother and her child in "
                             "their house. Rescuers found the mother's body and the child alive; rescue "
                             "vehicles could not get into the valley.", dead=1, rescued=1),
             R(1105, "fatal", "The hill stream overflowed and flooded the village."),
             R(989, "fatal", "The child was found alive and rescuers carried on working."),
         ]),
    dict(id="way-di", mm="ဝေဒီ", en="Way Di", ts="Launglon", area="Launglon north", hazard="both",
         reports=[R(1094, "affected", LIST27)]),
    dict(id="tha-byar", mm="သဗျာ", en="Tha Byar", ts="Launglon", area="Launglon north", hazard="both",
         reports=[
             R(1098, "severe", "Hillsides collapsed; low-lying parts under water a person's height deep. People "
                              "have been trapped on their houses since the night, and some are said to be "
                              "missing.", depth_ft=6),
             R(1055, "severe", "Search-and-rescue teams reached Tha Byar at about 11 am on 27 Sep and cleared "
                              "earth and rocks from the road by the monastery.", rescue="reached",
               roles=["access"]),
             R(1060, "severe", "Many houses buried by landslides."),
         ]),
    dict(id="pyin-sa-thi-maw", mm="ပဉ္စသီမော်", en="Pyin Sa Thi Maw", ts="Launglon", area="Launglon north",
         hazard="landslide", reports=[
             R(1056, "affected", "Landslide debris across the road at the village exit, cleared by rescue teams "
                                "on 27 Sep.", roles=["access"]),
         ]),
    dict(id="thea-pon", mm="သဲပုံ", en="Thea Pon", ts="Launglon", area="Launglon north", hazard="landslide",
         reports=[
             R(1110, "affected", "Landslide on the road up Inwa hill."),
             R(991, "affected", "A slide on Inwa hill buried land and destroyed orchards."),
         ]),
    dict(id="sit-pyay", mm="စစ်ပြဲ", en="Sit Pyay", ts="Launglon", area="Launglon north", hazard="flood",
         reports=[
             R(1161, "affected", "The whole village under water on the night of 26 Sep; belongings under the "
                                "houses washed away. Residents stayed awake for fear of landslides."),
         ]),

    # ================================================== Launglon town
    dict(id="launglon-town", mm="လောင်းလုံးမြို့", en="Launglon town", ts="Launglon", area="Launglon town",
         town="Launglon", hazard="both", reports=[
             R(1156, "affected", "Roads overtopped and water in houses across Launglon; families in low-lying "
                                "homes moved out in the night. Village roads and bridges are under water.",
               roles=["access"]),
             R(1091, "affected", "The town and about 20 villages in the south of the township are flooded."),
             R(960, "affected", "Rescue teams are stuck in Launglon town: the Poe Zar Pin slide blocks the road "
                                "south.", roles=["access"]),
             R(852, "affected", "More than 20 villages in the township are flooded. Most residents are in "
                               "relief camps and monasteries; food has run out.", roles=["relief", "needs"]),
         ]),

    # ================================================== Launglon, south of town
    dict(id="nyin-maw", mm="ညင်းမော်", en="Nyin Maw", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(1094, "affected", LIST27),
             R(970, "affected", "Photo of the village's condition on 27 Sep. The Poe Zar Pin slide lies on the "
                                "road between here and Launglon town."),
         ]),
    dict(id="ka-htaung-ni", mm="ကထောင်းနီ", en="Ka Htaung Ni", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(1094, "affected", LIST27)]),
    dict(id="ka-nyon-kyun", mm="ကညုံကျွန်း", en="Ka Nyon Kyun", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(1094, "affected", LIST27)]),
    dict(id="gawt-inn", mm="ဂေါ့အင်း", en="Gawt Inn", ts="Launglon", area="Launglon south", hazard="both",
         reports=[R(1094, "affected", LIST27)]),
    dict(id="auk-yay-phyu", mm="အောက်ရေဖြူ", en="Auk Yay Phyu", ts="Launglon", area="Launglon south",
         hazard="both", alias_mm="ရေဖြူ",
         match_note="The 27 Sep posts call it ရေဖြူ (Yay Phyu); the 28 Sep post names it အောက်ရေဖြူ, "
                    "MIMU's village 1.6 km from Kadet Nge Htein.",
         reports=[
             R(1094, "affected", LIST27),
             R(1088, "affected", "Some Kadet Nge [Htein] residents have moved here, a little over a mile away.",
               roles=["relief"]),
             R(994, "severe", "An emergency camp at the village school and on the pagoda hill shelters about "
                              "500 flood victims, who need help.", sheltering=500, roles=["relief", "needs", "school"]),
             R(820, "severe", "As of 28 Sep the rescue team from Dawei had got no further south than Auk Yay "
                            "Phyu.", rescue="reached"),
         ]),
    dict(id="ka-det-gyi", mm="ကဒက်ကြီး", en="Ka Det Gyi", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(1166, "affected", "People living near the hills have packed their belongings; some are moving out."),
             R(1094, "affected", LIST27),
         ]),
    # Several posts call it ကဒက်ငယ် (Ka Det Nge), once ကဒက်ငယ်ကြီး; local residents confirmed that this is Ka Det
    # Nge Htein, so those reports are here. Figures are read, never summed, across reports (see main()), so
    # the two bodies and "about 10 missing" of 27 Sep are not counted again on top of this village's own.
    dict(id="ka-det-nge-htein", mm="ကဒက်ငယ်ထိန်", en="Ka Det Nge Htein", ts="Launglon",
         area="Launglon south", hazard="landslide", alias_mm="ကဒက်ငယ် · ကဒက်ငယ်ကြီး",
         merge_note="Some posts call it ကဒက်ငယ် (Ka Det Nge), and the 9:30 am post of 27 Sep ကဒက်ငယ်ကြီး (Ka Det Nge "
                    "Gyi). Local residents confirmed these are Ka Det Nge Htein, so those reports are merged here "
                    "and its figures are not counted twice.",
         reports=[
             R(1150, "severe", "Designated red level (as Kadet Nge Gyi). Rescue teams had not reached it by 9:30 am on "
                              "27 Sep.", red=True, rescue="not-reached"),
             R(1094, "severe", LIST27),
             R(1084, "fatal", "About 10 residents buried in their houses by the landslide. The bodies of a child "
                             "and a woman have been found; villagers are searching for the rest themselves.",
               dead=2, missing=10),
             R(1103, "fatal", "Photos show waist-deep water in the village.", depth_ft=3),
             R(985, "fatal", "Heavy loss of life and property; tens of people missing, about 10 still "
                             "missing after two bodies were recovered."),
             R(853, "fatal", "Among the villages with deaths; red level.", red=True),
             R(855, "fatal", "Rescue teams from Dawei had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
             R(1102, "severe", "Landslides and flooding."),
             R(967, "fatal", "By the evening of 27 Sep dozens were missing and two bodies had been found.",
               dead=2, missing_text="dozens"),
             R(993, "fatal", "The hill beside the village collapsed, burying at least 50 houses. Dozens of "
                             "people are missing.", houses=50),
             R(828, "fatal", "An advance rescue team, bypassing the blocked road on foot through the forest, "
                            "reached the village at about 8 am on 28 Sep and began searching.",
               rescue="reached"),
             R(831, "fatal", "Red level. Three bodies recovered by 28 Sep; dozens of residents still missing.",
               dead=3, red=True),
         ]),
    dict(id="ka-det-nge-seik", mm="ကဒက်ငယ်ဆိပ်", en="Ka Det Nge Seik", ts="Launglon", area="Launglon south",
         hazard="both", reports=[
             R(1146, "severe", "Landslides, and serious flooding in low-lying parts."),
             R(1150, "severe", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(994, "severe", "Cut off by broken roads; needs food and drinking water.", roles=["needs", "access"]),
         ]),
    dict(id="taw-kye", mm="တောကျဲ", en="Taw Kye", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(1094, "affected", LIST27),
             R(819, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="tha-pyay-shaung", mm="သပြေရှောင်", en="Tha Pyay Shaung", ts="Launglon", area="Launglon south",
         hazard="both", reports=[R(1094, "affected", LIST27)]),
    dict(id="tha-kyet-taw", mm="သကျက်တော", en="Tha Kyet Taw", ts="Launglon", area="Launglon south",
         hazard="both", reports=[
             R(1094, "affected", LIST27),
             R(1146, "affected", "Landslides, and flooding in low-lying parts."),
             R(819, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="ra-be", mm="ရဘဲ", en="Ra Be", ts="Launglon", area="Launglon south", hazard="landslide",
         vt_hint="Tha Kyet Taw", reports=[
             R(819, "affected", "Landslides along the lower township; no relief has arrived.", roles=["needs"],
               rescue="not-reached"),
         ]),
    dict(id="za-lut", mm="ဇလွတ်", en="Za Lut", ts="Launglon", area="Launglon south", hazard="both",
         reports=[
             R(1094, "affected", LIST27),
             R(1146, "affected", "Landslides, and flooding in low-lying parts."),
             R(968, "fatal", "People dead and missing in floods and landslides, residents say."),
             R(855, "fatal", "Rescue teams had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
             R(819, "fatal", "No relief has arrived.", roles=["needs"]),
         ]),
    dict(id="za-lut-pyin-gyi", mm="ဇလွတ်ပြင်ကြီး", en="Za Lut Pyin Gyi", ts="Launglon",
         area="Launglon south", hazard="landslide", mimu_mm="ပြင်ကြီး", vt_hint="Za Lut", match="probable",
         match_note="Taken as MIMU's ပြင်ကြီး (Pyin Gyi) in Za Lut village tract. It may be the same place as "
                    "Za Lut itself.",
         reports=[
             R(832, "fatal", "Designated red level for floods and landslides.", red=True),
             R(853, "fatal", "Among the villages with deaths.", ),
         ]),
    dict(id="ti-zit", mm="တီဇစ်", en="Ti Zit", ts="Launglon", area="Launglon south", hazard="landslide",
         reports=[
             R(969, "severe", "A landslide destroyed orchards and some houses; residents are trapped."),
             R(832, "fatal", "Designated red level; deaths reported and some residents still missing.", red=True),
             R(855, "fatal", "Rescue teams had still not reached it on the morning of 28 Sep.",
               rescue="not-reached"),
         ]),
    dict(id="kyauk-ni-maw", mm="ကျောက်နီမော်", en="Kyauk Ni Maw", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(1174, "fatal", "A village between the hills and the sea. A landslide on the evening of 26 Sep "
                             "buried people and houses. Residents pulled out an elderly person and two "
                             "children; others are missing and the ground was still moving at 6 pm.",
               rescued=3, missing_text="some"),
             R(1162, "fatal", "Needs emergency rescue."),
             R(1150, "fatal", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(1095, "fatal", "Slides since about 5 pm on 26 Sep are still coming down. A child and a man are "
                             "missing; no rescue is possible yet. The road to Shin Maw is destroyed.",
               missing=2, roles=["access"]),
             R(1101, "fatal", "Contact with the village was lost from the morning of 27 Sep.", roles=["comms"]),
             R(853, "fatal", "Among the villages with deaths; red level.", red=True),
         ]),
    dict(id="nyaw-pyin", mm="ညောပြင်", en="Nyaw Pyin", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(1100, "severe", "Landslides."),
             R(1150, "severe", "Designated red level; not reached by rescue teams by 9:30 am on 27 Sep.",
               red=True, rescue="not-reached"),
             R(992, "severe", "Deaths reported but not confirmed."),
             R(968, "fatal", "People dead and missing, residents say."),
             R(817, "fatal", "A landslide at Thayet Pin Kone (Shit Pan Gu) on 27 Sep killed two women, one of "
                           "them elderly. The village, already hit by the war, is short of food and drinking "
                           "water, and no relief has arrived. Contact was lost on the morning of 28 Sep.",
               dead=2, roles=["needs", "comms"], rescue="not-reached"),
         ]),

    # ================================================== Launglon, north-west coast
    dict(id="tha-bawt-seik", mm="သဘော့ဆိပ်", en="Tha Bawt Seik", ts="Launglon", area="Launglon north-west",
         hazard="both", reports=[
             R(978, "affected", "Near Maungmagan beach; named among villages hit by floods and landslides."),
         ]),
    dict(id="kayin-gyi", mm="ကရင်ကြီး", en="Kayin Gyi", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(1045, "severe", "The hills east of the village collapsed at about 9 pm on 26 Sep and 2 am on "
                              "27 Sep, burying nearly 30 houses, two-wheel tractors and motorcycles. No one was "
                              "hurt. About 30 households, some 60 people, moved to the monastery and need help.",
               houses=30, sheltering=60, roles=["relief", "needs"]),
             R(996, "severe", "About 30 houses buried; more than 60 people moved to the monastery."),
             R(847, "severe", "Another slide on the night of 27 Sep covered the whole eastern half of the "
                             "village, destroying houses, the bridge and the village roads. Residents are "
                             "living at the monastery and urgently need food.",
               houses_text="east half of village", roles=["access", "relief", "needs"]),
         ]),
    dict(id="maungmagan", mm="မောင်းမကန်", en="Maungmagan", ts="Launglon", area="Launglon north-west",
         hazard="flood", reports=[
             R(999, "affected", "The blue-green sea at Maungmagan and nearby beaches turned muddy yellow.",
               roles=["observe"]),
         ]),
    dict(id="kyet-hlut", mm="ကြက်လွတ်", en="Kyet Hlut", ts="Launglon", area="Launglon south",
         hazard="landslide", mimu_mm="ကြက်လွှတ်", match="variant",
         match_note="MIMU spells it ကြက်လွှတ် (Kyet Hlut), in Kyauk Mat Tat village tract.",
         reports=[
             R(1092, "affected", "Hills have been collapsing since the evening of 25 Sep as far as Kyet Lut; no "
                                "rescue has been possible."),
         ]),

    # ================================================== Thayetchaung
    dict(id="thayetchaung-town", mm="သရက်ချောင်းမြို့", en="Thayetchaung town", ts="Thayetchaung",
         area="Thayetchaung", town="Thayetchaung", hazard="flood", reports=[
             R(1125, "severe", "Water about 6 ft deep in some streets. People trapped in their homes are "
                              "appealing for help on Facebook Live.", depth_ft=6),
             R(1071, "severe", "Myo Ma, Kyauk Myaung and Pan Taw wards flooded; households moving out."),
             R(955, "severe", "Military government figures: five town wards flooded 6–8 ft and more than "
                              "18,000 people affected.", depth_ft=8, affected=18000),
             R(911, "severe", "Still flooded on 28 Sep, along with the villages on the Union highway."),
         ]),
    dict(id="shin-moke-tee", mm="ရှင်မုတ္ထီး", en="Shin Moke Tee", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", mimu_mm="ရှင်မုတ္တီး", match="variant",
         match_note="MIMU spells it ရှင်မုတ္တီး. The 27 Sep road post places it in Dawei Township, as MIMU does; "
                    "other posts list it with Thayetchaung.",
         reports=[
             R(1069, "affected", "Named among flooded villages on the Union highway."),
             R(1030, "affected", "Flooding on the road stretch."),
             R(911, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="yaung-maw", mm="ရောင်းမော်", en="Yaung Maw", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", reports=[
             R(1069, "affected", "Named among flooded villages east of the Union highway."),
             R(1030, "affected", "Flooding on the road stretch."),
             R(912, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="nyaung-zin", mm="ညောင်ဇင်", en="Nyaung Zin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(1069, "affected", "Named among flooded villages."),
             R(911, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyar-inn", mm="ကြာအင်း", en="Kyar Inn", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(1124, "affected", "Hill-stream water has flooded the paddy fields and entered houses."),
             R(912, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyet-sar-pyin", mm="ကြက်စားပြင်", en="Kyet Sar Pyin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(1030, "affected", "Flooding on the Dawei–Myeik road stretch.")]),
    dict(id="kin-shey", mm="ကင်းရှေ့", en="Kin Shey", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(1067, "severe", "Water came into houses from about midnight; by dawn on 27 Sep the whole ground "
                              "floor was under water, over a person's height. Families moved children to houses "
                              "in town.", depth_ft=6),
             R(912, "severe", "Still flooded on 28 Sep."),
         ]),
    dict(id="moe-shwe-kone", mm="မိုးရွှေကုန်း", en="Moe Shwe Kone", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="probable", ward="Maw Shi Kone Ward",
         match_note="Not in MIMU village points. Taken as Maw Shi Kone Ward (မော်ရှီကုန်း) of Thayetchaung "
                    "town, the closest MIMU name; shown at the ward centre.",
         reports=[
             R(1070, "affected", "Houses near the stream are moving out."),
             R(912, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="saw-hpyar", mm="စော်ဖျား", en="Saw Hpyar", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(1070, "affected", "Water reached houses that had never flooded; people are moving little by "
                                "little to safer places."),
             R(912, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="kyauk-hlay-kar", mm="ကျောက်လှေကား", en="Kyauk Hlay Kar", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(947, "affected", "Named among flooded villages east of the Union highway."),
             R(912, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="yan-taung", mm="ရန်တောင်", en="Yan Taung", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(1069, "affected", "Named among flooded villages."),
                                  R(911, "affected", "Still flooded on 28 Sep.")]),
    dict(id="thin-kyun", mm="သင်းကျွန်း", en="Thin Kyun", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(1027, "affected", "Vehicles from Dawei turned back here on 27 Sep; 2–4 ft of water on the road, "
                                "falling about 2 ft by 3:30 pm.", depth_ft=4, roles=["access"]),
             R(911, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="tha-yet-hnit-khwa", mm="သရက်နှစ်ခွ", en="Tha Yet Hnit Khwa", ts="Thayetchaung",
         area="Thayetchaung", hazard="flood", reports=[
             R(1124, "affected", "Paddy fields flooded and water inside houses."),
             R(1027, "affected", "Flooding reported by drivers."),
             R(911, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="oke-tu", mm="ဥတ္တူ", en="Oke Tu", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(1124, "affected", "Paddy fields flooded and water inside houses."),
                  R(912, "affected", "Still flooded on 28 Sep.")]),
    dict(id="ti-tut-pyin", mm="တီတွတ်ပြင်", en="Ti Tut Pyin", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[R(1126, "affected", "Paddy fields flooded and water inside houses."),
                                  R(911, "affected", "Still flooded on 28 Sep (west of the road).")]),
    dict(id="pe-det", mm="ပဲဒက်", en="Pe Det", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[
             R(1066, "affected", "Villages flooded all the way from past the Pauk Taing bridge checkpoint to "
                                "beyond Pe Det."),
             R(1026, "affected", "Vehicles coming up from Myeik stranded near Pe Det on 27 Sep.", roles=["access"]),
             R(911, "affected", "Still flooded on 28 Sep."),
         ]),
    dict(id="htee-hpa-doe", mm="ထီးဖဒို", en="Htee Hpa Doe", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="unlocated",
         match_note="No village of this name, or a close spelling, in MIMU for the region.",
         reports=[R(957, "affected", "Photo of the flooded village sent in by residents."),
                  R(912, "affected", "Still flooded on 28 Sep.")]),
    dict(id="ka-nyin-chaung", mm="ကညင်ချောင်း", en="Ka Nyin Chaung", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(913, "severe", "The bridge at Ka Nyin Chaung on Union Road No. 8 was destroyed, cutting the "
                             "Dawei–Myeik road.", roles=["access"]),
         ]),
    dict(id="taung-pyauk", mm="တောင်ပျောက်", en="Taung Pyauk area", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", match="approx", approx_vt="Kayin Taung Pyauk",
         match_note="The posts name the Taung Pyauk area (about 10 villages) without listing them. Shown at "
                    "the centre of Kayin Taung Pyauk village tract.",
         reports=[
             R(949, "affected", "Heavy rain since 24 Sep; flooding from the morning of 27 Sep. About 10 "
                                "villages, where the military restricts the transport of food and medicine. "
                                "Phone lines down; buffalo and cattle lost, people safe.",
               roles=["comms"], villages=10),
             R(914, "severe", "Rope bridges destroyed and flooding severe. Most villages have no phone or "
                             "internet, so details are unknown.", roles=["access", "comms"]),
         ]),

    # ================================================== Dawei town
    dict(id="dawei-town", mm="ထားဝယ်မြို့", en="Dawei town", ts="Dawei", town="Dawei", area="Dawei town",
         hazard="flood", reports=[
             R(1117, "severe", "Drains overflowed and main roads went under water in some wards. Elderly people "
                              "and children trapped at home were brought out by welfare groups. Flooding in the "
                              "Mae Di Land private hospital compound on Ka Myaw Kin road; strong winds brought "
                              "down large trees.", roles=["access"]),
             R(933, "severe", "Water entered wards from the morning of 27 Sep; by evening most wards and "
                              "several streams were flooded. The Zeyawaddy monastic school near the Shwe Taung "
                              "Zar pagoda and the Ghositarama Pali University (Taik Thit) are flooded. Power was "
                              "cut to the town and surrounding villages, and some schools closed."),
             R(1038, "severe", "Most wards still flooded."),
             R(925, "severe", "Still raining and windy on the morning of 28 Sep; no electricity."),
         ]),
    dict(id="kyauk-maw-ward", mm="ကျောက်မော်ရပ်ကွက်", en="Kyauk Maw ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ကျောက်မော်ရပ်ကွက်", reports=[
             R(934, "affected", "A resident: water is everywhere, even where it has never come before."),
         ]),
    dict(id="bon-maw-ward", mm="ဘုမ္မော်ရပ်ကွက်", en="Bon Maw ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ဘုမ္မော်ရပ်ကွက်", reports=[
             R(920, "severe", "Single-storey houses under water on the morning of 28 Sep. The football ground "
                              "and walls of Basic Education High School No. 2 are submerged, and single-storey "
                              "houses on Mya Sabai street are flooded.", roles=["school"]),
         ]),
    dict(id="ka-nyon-ward", mm="ကညုံရပ်ကွက်", en="Ka Nyon ward", ts="Dawei", area="Dawei town",
         hazard="flood", ward_mm="ကညုံရပ်ကွက်", reports=[
             R(936, "severe", "Near the Taik Thit monastery, 10 people including elderly people and a child "
                              "were rescued on the evening of 27 Sep by the regional emergency team and the "
                              "Red Cross.", rescued=10),
             R(922, "severe", "Water in compounds on Taik Thit Kyaung road; some single-storey houses "
                              "submerged. A resident of more than ten years has never seen flooding like it."),
         ]),
    dict(id="kyet-sa-pyin-ward", mm="ကြက်စားပြင်ရပ်ကွက်", en="Kyet Sa Pyin ward", ts="Dawei",
         area="Dawei town", hazard="flood", ward_mm="ကြက်စားပြင်ရပ်ကွက်", reports=[
             R(920, "severe", "Some single-storey houses under water on the morning of 28 Sep."),
         ]),
    dict(id="ka-yat-pyin-ward", mm="ကရပ်ပြင်ရပ်ကွက်", en="Ka Yat Pyin ward", ts="Dawei", area="Dawei town",
         hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards (the boundaries predate newer wards).",
         reports=[R(920, "severe", "Single-storey houses under water; side streets of Ka Yat Pyin (North) "
                                   "flooded.")]),
    dict(id="shan-ma-le-swe-ward", mm="ရှမ္မလည်ဆွဲရပ်ကွက်", en="Shan Ma Le Swe ward", ts="Dawei",
         area="Dawei town", hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards.",
         reports=[R(920, "severe", "Single-storey houses under water; side streets flooded.")]),
    dict(id="khon-win-dat-ward", mm="ခုံဝင်းဒပ်ရပ်ကွက်", en="Khon Win Dat ward", ts="Dawei", area="Dawei town",
         hazard="flood", match="unlocated",
         match_note="Not among MIMU's 15 Dawei town wards. The post places it behind the regional military "
                    "government office.",
         reports=[R(924, "affected", "Knee-deep water since 27 Sep on the road east of the Shwe Hlyit Hmyaung "
                                     "pagoda.")]),
    dict(id="pauk-taing", mm="ပေါက်တိုင်း", en="Pauk Taing bridge", ts="Dawei", area="Dawei–Thayetchaung road",
         hazard="flood", bridge="Pauk Taing Bridge", reports=[
             R(1066, "affected", "The checkpoint at Pauk Taing bridge, at the entrance to Dawei, marks the "
                                "northern end of the flooded stretch that runs south past Pe Det.",
               roles=["access"]),
         ]),

    # ================================================== Dawei, east (road to Htee Khee)
    dict(id="za-lun", mm="ဇလွန်း", en="Za Lun", ts="Dawei", area="Dawei east", hazard="flood",
         reports=[R(1122, "affected", "Flooded; water over the Dawei–Htee Khee road in the forest east of "
                                     "Dawei.", roles=["access"])]),
    dict(id="ta-laing-taung", mm="တလိုင်းတောင်", en="Ta Laing Taung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[R(1122, "affected", "Flooded; water over the Dawei–Htee Khee road.",
                                    roles=["access"])]),
    dict(id="pa-kar-ri", mm="ပကာရီ", en="Pa Kar Ri", ts="Dawei", area="Dawei east", hazard="flood",
         reports=[
             R(1122, "affected", "Flooded, according to residents' photos and video."),
             R(859, "severe", "Water entered on the morning of 27 Sep and rose fast. By night houses on higher "
                             "ground were flooded to the first floor and low-lying houses were completely "
                             "submerged. The whole village is under water and the border road is impassable.",
               depth_ft=10, roles=["access"]),
         ]),
    dict(id="san-chi", mm="ဆန်းချီ", en="San Chi", ts="Dawei", area="Dawei east", hazard="flood",
         vt_hint="Pa Kar Ri", reports=[
             R(1012, "affected", "Water flowing over the San Chi bridge.", roles=["access"]),
             R(864, "severe", "Video shows the San Chi village bridge submerged.", roles=["access"]),
         ]),
    dict(id="yam-ma-zu", mm="ရမ္မဇူ", en="Yam Ma Zu", ts="Dawei", area="Dawei east", hazard="both",
         reports=[R(865, "affected", "Flooded. A landslide inside the Yam Ma Zu private school compound has "
                                    "closed the school.", roles=["school"])]),
    dict(id="leik-kyei-pyaung", mm="လိပ်ကြယ်ပြောင်", en="Leik Kyei Pyaung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[R(865, "affected", "Flooded.")]),
    dict(id="thin-gan-tone", mm="သင်္ကန်းတုံး", en="Thin Gan Tone", ts="Dawei", area="Dawei east",
         hazard="flood", match="unlocated",
         match_note="Not in MIMU village points; the post places it in Pa Kar Ri village tract.",
         reports=[R(865, "affected", "Flooded.")]),
    dict(id="tha-yet-ngoke", mm="သရက်ငုတ်", en="Tha Yet Ngoke", ts="Dawei", area="Dawei east",
         hazard="landslide", reports=[
             R(866, "affected", "A landslide on the main road nearby leaves room for only one vehicle at a "
                               "time.", roles=["access"]),
         ]),

    # ================================================== Yebyu
    dict(id="kaleinaung", mm="ကလိန်အောင်", en="Kaleinaung", ts="Yebyu", town="Kaleinaung", area="Yebyu",
         hazard="flood", reports=[
             R(1128, "affected", "Water over the road in places on the Union highway and at Kaleinaung, but "
                                "traffic can still pass.", roles=["access"]),
             R(1016, "affected", "Nothing else unusual in Yebyu Township, residents say."),
         ]),

    # ================================================== Palaw (Myeik District)
    dict(id="palauk", mm="ပလောက်", en="Palauk", ts="Palaw", town="Palauk", area="Palaw", hazard="flood",
         reports=[
             R(1138, "affected", "Flooding: water in houses and over the main road, residents' records show."),
             R(1026, "affected", "Some vehicles stranded beyond Palauk, at the foot of Bok Taung.",
               roles=["access"]),
         ]),
    dict(id="pa-wut-kone", mm="ပဝတ်ကုန်း", en="Pa Wut Kone", ts="Palaw", area="Palaw", hazard="flood",
         reports=[R(1031, "affected", "Flooding over broken stretches of the road between Palaw and Pala.",
                    roles=["access"])]),
    dict(id="ka-de", mm="ကဒဲ", en="Ka De", ts="Palaw", area="Palaw", hazard="flood",
         reports=[R(1031, "affected", "Flooding over broken stretches of the road between Palaw and Pala.",
                    roles=["access"])]),

    # ================================================== Tanintharyi (Myeik District)
    dict(id="tanintharyi-town", mm="တနင်္သာရီမြို့", en="Tanintharyi town", ts="Tanintharyi",
         town="Tanintharyi", area="Tanintharyi", hazard="flood", reports=[
             R(1136, "affected", "The Tanintharyi River, which rises in Dawei District, has been rising since "
                                "26 Sep and on 27 Sep was about 2 ft below its 17 ft alert mark. Low-lying "
                                "wards of the town are flooded.", river_ft=15),
             R(844, "affected", "Phone and internet lines cut from the evening of 27 Sep.", roles=["comms"]),
         ]),
    dict(id="tha-kyet", mm="သကျက်", en="Tha Kyet", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[R(839, "affected", "Stream water came in on the night of 27 Sep; roads knee-deep and some "
                                    "places impassable.", depth_ft=2)]),
    dict(id="ta-ku", mm="တကူ", en="Ta Ku", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         vt_hint="Ta Ku", reports=[R(842, "affected", "The Tanintharyi River began rising on 27 Sep and is rising "
                                                     "fast; the paddy fields are full of water.")]),
    dict(id="thar-ra-bwin", mm="သာရဘွင်", en="Thar Ra Bwin", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[
             R(841, "affected", "The bridge linking Thar Ra Bwin with Ashay Kan (the east-bank village) is under "
                               "water, and water is entering some roads.", roles=["access"]),
         ]),
]

# ---------------------------------------------------------------------------
# 29 Sep update. What the later 28 Sep posts and the 29 Sep posts add about the
# places above (appended to their reports; main() re-sorts them by day and post),
# then the places they name for the first time.
# ---------------------------------------------------------------------------
LIST28 = "Named among the Launglon villages hit by floods and landslides in the 28 Sep explainer."
RECEDED_28 = "Among the worst-flooded places; the water fell on the evening of 28 Sep."
TNI_TRACTS = ("Among 20-odd villages in nine tracts along the Tanintharyi River and its streams under water after "
              "three days of rain.")

MORE = {
    # ---------------------------------------------- Launglon
    "ka-myaw-gyi": [R(803, "affected", RECEDED_28, roles=["receding"])],
    "way-di": [
        R(803, "affected", RECEDED_28, roles=["receding"]),
        R(805, "affected", "By the Dawei River. From about 9 pm on 26 Sep the water rose to nearly 5 ft on the road "
                           "between Kone Zayat and Way Di, cutting the village off; most residents moved to the "
                           "monastery. About 20 cattle were swept away; seven were saved as the water fell on "
                           "28 Sep. No one was hurt.", depth_ft=5, roles=["access", "relief", "receding"]),
    ],
    "min-yat": [
        R(628, "fatal", "One body recovered.", dead=1),
        R(803, "fatal", RECEDED_28, roles=["receding"]),
        R(495, "fatal", "One body recovered (29 Sep round-up).", dead=1),
    ],
    "tha-byar": [
        R(592, "severe", "On 27 Sep rescuers had to borrow two tractors to clear the road near Tha Byar; a backhoe "
                         "went down on the morning of 28 Sep.", roles=["access"]),
        R(803, "severe", RECEDED_28, roles=["receding"]),
        R(549, "fatal", "A mother and son, the wife and son of Ko Aung Shein (Ko Aung Thar) of Kayin Gyi, have been "
                        "missing since the slide of 26 Sep and were still not found on the morning of 29 Sep.",
          missing=2),
        R(552, "fatal", "At least four houses almost completely destroyed and nearly 200 filled with silt; rubber, "
                        "betel-nut and cashew orchards buried. Residents say this slide is bigger than 1997's.",
          houses=4),
        R(495, "fatal", "A mother and son missing (29 Sep round-up).", missing=2),
        R(434, "fatal", "Still not found four days on.", missing=2),
    ],
    "thea-pon": [
        R(516, "severe", "A slide on Inwa hill on the night of 26 Sep brought down monastery buildings at the foot "
                        "of the hill and buried orchards near the village; no one was hurt. Damage to outlying "
                        "orchards is unknown, and the road up the hill has collapsed.", roles=["access"]),
    ],
    "launglon-town": [R(803, "affected", "The water fell on the evening of 28 Sep.", roles=["receding"])],
    "nyin-maw": [
        R(590, "affected", "The rescue teams' base: relief supplies are collected here and handed out.",
          rescue="reached", roles=["relief"]),
        R(461, "affected", "Backhoes have cleared the road as far as Nyin Maw.", rescue="reached"),
        R(444, "affected", "The slide debris on the hill road between Nyin Maw and Ti Zit still has to be cleared.",
          roles=["access"]),
    ],
    "ka-det-nge-htein": [
        R(594, "fatal", "A rescue volunteer names it the worst hit, with the most deaths."),
        R(701, "fatal", "31 houses completely destroyed; the buried ground covers about five football pitches, "
                        "starting beside the Kadet Nge hill monastery.", houses=31),
        R(693, "fatal", "Three more bodies found on 28 Sep, five in all; 13 people went missing in the slide on "
                        "the night of 26 Sep. The Zambu Thiri team recovered 12-year-old Maung Ar Kar Min and a "
                        "monk in the afternoon; residents found the other three. The search resumes with "
                        "residents on 29 Sep.", dead=5),
        R(628, "fatal", "Five bodies recovered; dozens missing.", dead=5, missing_text="dozens"),
        R(618, "fatal", "Red level: bodies found and dozens still missing.", red=True),
        R(812, "fatal", "Emergency search and rescue under way since the morning of 28 Sep.", rescue="reached"),
        R(555, "fatal", "Red level; the search for the missing continues on 29 Sep.", red=True),
        R(493, "fatal", "Ten bodies recovered and three still missing. An advance team of a dozen or so has been "
                       "working here since 28 Sep.", dead=10, missing=3, rescue="reached"),
    ],
    "ka-det-gyi": [
        R(717, "fatal", "The bodies of a mother and son, Daw Khin Aye, over 70, and U Myo Thein, about 45, a deputy "
                        "village administrator, were found under slide earth in their rubber and durian orchard a "
                        "few miles from the village on the evening of 28 Sep. They were cremated the same day.",
          dead=2),
        R(636, "fatal", "A slide filled an orchard; a mother and son died.", dead=2),
        R(494, "fatal", "Two bodies recovered (29 Sep round-up).", dead=2),
    ],
    "taw-kye": [R(639, "affected", "Slides; residents have had no help.", roles=["needs"])],
    "tha-kyet-taw": [R(646, "affected", "No emergency rescue team had arrived by the evening of 28 Sep.",
                       rescue="not-reached")],
    "ra-be": [R(646, "affected", "No emergency rescue team had arrived by the evening of 28 Sep.",
                rescue="not-reached")],
    "za-lut": [
        R(646, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(465, "fatal", "Damage reported here too, north of Kyauk Ni Maw."),
    ],
    "za-lut-pyin-gyi": [
        R(645, "fatal", LIST28),
        R(465, "fatal", "Damage reported (as Pyin Gyi, north of Kyauk Ni Maw)."),
    ],
    "kyauk-ni-maw": [
        R(558, "fatal", "About 50 houses buried since the evening of 26 Sep and at least five people missing. The "
                        "worst slide hit the crowded junction of the lower road (In Ni Twin) and the upper road (by "
                        "the school). No search has been possible; more than 200 residents are in the monastery "
                        "and urgently need food and medicine.",
          houses=50, missing=5, sheltering=200, rescue="not-reached", roles=["relief", "needs"]),
        R(628, "fatal", "Two bodies recovered.", dead=2),
        R(646, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(536, "fatal", "Word reaching Nyaw Pyin: about 50 houses collapsed; eight people buried, two dead and six "
                        "missing (unconfirmed).", dead=2, missing=6),
        R(495, "fatal", "The 29 Sep round-up lists eight residents missing and no bodies recovered.",
          dead=0, missing=8),
        R(452, "fatal", "More than 50 houses damaged and at least five people missing. Burned by the junta in late "
                       "2024, the village had been rebuilding for barely a year.", houses=50, missing=5),
        R(457, "fatal", "More than 200 villagers at the monastery, which feeds them from its own rice. About five "
                       "dead or missing, one from this house, one from that. No rescue team has got in; those left "
                       "dig by hand, with no backhoe.", sheltering=200, rescue="not-reached",
          roles=["relief", "needs"]),
        R(461, "fatal", "Neighbourhoods are cut off from each other by debris. Nearly every village on the road from "
                       "Dawei has slides, so rescuers may take days to get here.", roles=["access"]),
        R(465, "fatal", "Many bridges destroyed on the way down to Shin Maw.", roles=["access"]),
    ],
    "nyaw-pyin": [
        R(564, "fatal", "Hills collapsed here too."),
        R(628, "fatal", "Two bodies recovered.", dead=2),
        R(646, "fatal", "No emergency rescue team had arrived by the evening of 28 Sep.", rescue="not-reached"),
        R(526, "fatal", "A fishing village near Grandfather Beach, 30-odd miles south of Launglon, burned by the junta "
                       "again and again since the coup. The slide and strong winds of 26 Sep destroyed more than 30 "
                       "houses; two residents were killed.", dead=2, houses=30),
        R(532, "fatal", "At least two slides round the village, and more towards Grandfather Beach; the one beside "
                        "the road killed the two."),
        R(534, "fatal", "The roads between villages are blocked, so aid cannot get in. A fishing village with no "
                        "work in the monsoon and no money to rebuild.", roles=["needs", "access"]),
        R(495, "fatal", "Two bodies recovered (29 Sep round-up).", dead=2),
    ],
    "ti-zit": [
        R(442, "fatal", "A beach village about four miles south-west of Launglon, over the hill from Nyin Maw. Slides "
                       "from the surrounding hills on the night of 26 Sep buried its streets and the hill road, "
                       "cutting it off.", roles=["access"], rescue="not-reached"),
        R(443, "fatal", "No cars or motorcycles can get out, and on foot people sink in the mud; villagers had to "
                       "carry home on a stretcher a body brought back from hospital."),
        R(445, "fatal", "The phone tower runs on fuel that will soon run out; people are living on what the village "
                       "shops had in stock.", roles=["comms", "needs"]),
        R(446, "fatal", "Eight houses destroyed and nearly 40 buried, with many orchards.", houses=40),
        R(447, "fatal", "Nearly 600 households, more than 1,000 people, need emergency food.", roles=["needs"]),
    ],
    "kayin-gyi": [
        R(588, "severe", "Hills also collapsed on the Kayin Gyi and Kan Pa Ni side, where teams from Maungmagan are "
                         "working."),
        R(649, "severe", "About 100 junta troops entered Kyauk Sin village tract, which includes Kayin Gyi, saying "
                         "they had come to help; residents fled, and the troops stayed at Kyauk Sin."),
    ],
    "maungmagan": [
        R(588, "affected", "Hills have collapsed on this side too; the Maungmagan rescue teams are working here."),
    ],
    # ---------------------------------------------- Dawei
    "dawei-town": [
        R(789, "severe", "Rain stopped from midday on 28 Sep and the water began to fall; rain returned in the "
                         "evening.", roles=["receding"]),
        R(713, "severe", "Electricity off since about 4 pm on 27 Sep and some phone lines down, still on the evening "
                         "of 28 Sep.", roles=["comms"]),
        R(705, "severe", "More than 600 flood victims, moved out overnight on 27 Sep, are sheltering at Pahtoe "
                         "Kyaung, Mattaya Kyaung, Zambu Htein Lin Kyaung, the Moe Kaung meditation centre and Dhamma "
                         "Sekya Kyaung and need food, clothes and medicine; the Red Cross is giving health care. "
                         "Wards still flooded on the evening of 28 Sep.", sheltering=600, roles=["relief", "needs"]),
        R(604, "severe", "Knee-deep water inside houses at the bend of Post Office Road on 28 Sep; a resident of "
                         "about 80 has never seen the like."),
        R(541, "severe", "Water falling in the town wards on the morning of 29 Sep. The sun is out and most "
                         "evacuees have gone home to clean up. Power still off at midday.", roles=["receding"]),
    ],
    "bon-maw-ward": [
        R(710, "severe", "Residents still at home on streets 2, 4, 5 and 6 need drinking water and food parcels.",
          roles=["needs"]),
        R(606, "severe", "Every street under water on 28 Sep."),
        R(546, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "ka-nyon-ward": [
        R(707, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(546, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "kyet-sa-pyin-ward": [
        R(707, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(710, "severe", "People still at home need food parcels.", roles=["needs"]),
        R(542, "severe", "Houses under water from the night of 27 Sep; water falling in town wards on 29 Sep.",
          roles=["receding"]),
    ],
    "ka-yat-pyin-ward": [R(707, "severe", "Residents of Ka Yat Pyin South and North moved out overnight on 27 Sep.",
                           roles=["relief"])],
    "shan-ma-le-swe-ward": [R(707, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"])],
    "khon-win-dat-ward": [
        R(707, "severe", "Residents moved out overnight on 27 Sep.", roles=["relief"]),
        R(546, "severe", "Water falling on the morning of 29 Sep.", roles=["receding"]),
    ],
    "za-lun": [R(714, "affected", "Cars and motorcycles could not get through on the road between Byaw Taw Wa and "
                                  "Za Lun on the evening of 28 Sep.", roles=["access"])],
    "pa-kar-ri": [R(658, "severe", "Villages in the tract are flooded and cut off from each other; residents in "
                                   "monasteries need food.", roles=["relief", "needs"])],
    # ---------------------------------------------- Thayetchaung
    "thayetchaung-town": [
        R(749, "severe", "The whole market flooded: rice, oil, eggs and other food lost. Wells are under water, so "
                         "drinking water is scarce.", roles=["needs"]),
        R(777, "severe", "The local Myat Parami charity can move only town-ward residents to safety; it has no boats "
                         "to reach the villages, and the district's teams are in Launglon.", roles=["needs"]),
        R(569, "fatal", "A man of about 60 with a mental illness was swept away and died, and a 90-year-old woman "
                        "died of exhaustion as she moved within her flooded house.", dead=2),
        R(468, "fatal", "The water has fallen, but the power is off, so phone lines are still down. Flooding ran "
                       "2–8 ft from midnight on 26 Sep to the morning of 28 Sep: it dipped on the evening of 27 Sep, "
                       "rose again on the morning of 28 Sep and fell from that afternoon, when the clean-up of mud "
                       "and fallen trees began.", roles=["receding", "comms"]),
        R(474, "fatal", "Flooded villages need drinking water, food and clothes, and help clearing the silt.",
          roles=["needs"]),
        R(498, "fatal", "Two dead in the town (29 Sep round-up).", dead=2),
    ],
    "saw-hpyar": [
        R(751, "fatal", "One resident killed by trees brought down by strong winds on the night of 27 Sep.", dead=1),
        R(763, "fatal", "Water starting to fall on 28 Sep, but still impassable while the rain goes on.",
          roles=["receding"]),
        R(568, "fatal", "A couple in their 50s killed by a falling tree.", dead=2),
        R(498, "fatal", "Two dead (29 Sep round-up).", dead=2),
    ],
    "kin-shey": [R(763, "severe", "Water starting to fall on 28 Sep, but still impassable while the rain goes on.",
                   roles=["receding"])],
    "ka-nyin-chaung": [
        R(568, "fatal", "A couple drowned.", dead=2),
        R(498, "fatal", "Two dead (29 Sep round-up).", dead=2),
    ],
    "kyar-inn": [
        R(760, "severe", "Water over a person's height on the road to Nyaung Zin and phone lines cut since 27 Sep. A "
                         "resident: the whole village is trapped inside; no one can get out.",
          depth_ft=6, roles=["access", "comms"]),
    ],
    "kyet-sar-pyin": [
        R(469, "affected", "A resident: the water has fallen and she has heard from home, but with the power out the "
                          "phones still don't work.", roles=["receding", "comms"]),
    ],
    "kyauk-hlay-kar": [R(572, "affected", "A house destroyed by a falling tree.")],
    "taung-pyauk": [
        R(767, "severe", "Phones and internet cut since the morning of 27 Sep. The area is held by resistance forces "
                         "and has long been under junta blockade.", roles=["comms"]),
        R(574, "severe", "Water still not falling on the evening of 28 Sep; rescue teams cannot move people trapped "
                         "in some villages.", roles=["needs"]),
    ],
    "pe-det": [R(778, "affected", "Residents asked for help, but water over the highway stopped the Myat Parami team "
                                  "getting there.", roles=["needs"])],
    # ---------------------------------------------- Tanintharyi
    "tanintharyi-town": [
        R(484, "affected", "Some low-lying residents have moved to higher ground for now.", roles=["relief"]),
        R(480, "affected", "At about 3 pm on 29 Sep the river stood above 26 ft, more than 2 ft over its 24 ft danger "
                          "mark. Rain stopped the day before, but water coming down from the Dawei side keeps it "
                          "rising. With the town's gates shut and water pumped out, the town itself is drier than "
                          "in August.", river_ft=26),
    ],
    "tha-kyet": [
        R(505, "affected", TNI_TRACTS),
        R(508, "severe", "Low-lying houses under water in some villages of the tract and residents moving to higher "
                        "ground: knee-deep the day before, waist-deep on 29 Sep and a person's height in low spots.",
          depth_ft=6),
    ],
    "ta-ku": [
        R(505, "affected", TNI_TRACTS),
        R(506, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so people "
                          "travel by boat and raft.", roles=["access"]),
    ],
    "thar-ra-bwin": [
        R(505, "affected", TNI_TRACTS),
        R(506, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so people "
                          "travel by boat and raft.", roles=["access"]),
    ],
}
_BY = {s["id"]: s for s in SITES}
for _k, _rs in MORE.items():
    _BY[_k]["reports"].extend(_rs)

TNI_LOW = ("Low-lying houses under water in some villages of the tract and residents moving to higher ground: "
           "knee-deep the day before, waist-deep on 29 Sep and a person's height in low spots.")
SITES += [
    # ================================================== Launglon
    dict(id="tha-win", mm="သဝင်", en="Tha Win", ts="Launglon", area="Launglon south", hazard="both",
         reports=[R(645, "affected", LIST28)]),
    dict(id="auk-kyauk-wut", mm="အောက်ကျောက်ဝပ်", en="Auk Kyauk Wut", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(564, "affected", "Hills collapsed here too."),
             R(536, "affected", "Hills beside the village collapsed, but no houses in the village fell."),
         ]),
    dict(id="kyauk-wut-pyin", mm="ကျောက်ဝပ်ပြင်", en="Kyauk Wut Pyin", ts="Launglon", area="Launglon south",
         hazard="landslide", reports=[
             R(465, "affected", "The whole road on from Kyauk Ni Maw through Kyauk Wut Pyin is in difficulty, and many "
                               "places still cannot be reached.", roles=["access"]),
         ]),
    dict(id="pa-nyit", mm="ပညစ်", en="Pa Nyit", ts="Launglon", area="Launglon north-west", hazard="landslide",
         reports=[
             R(795, "severe", "Slides in the village and on the road after the heavy rain of 27 Sep; residents are "
                              "moving to safety."),
             R(796, "severe", "Two houses buried, no one hurt. Road slides have cut off parts of the area.",
               houses=2, roles=["access", "comms"]),
             R(643, "severe", "Two houses buried on 27 Sep; no one was killed, but residents are moving to safety.",
               houses=2),
             R(645, "severe", LIST28),
         ]),
    dict(id="kan-pa-ni", mm="ကမ်းပနီ", en="Kan Pa Ni", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(797, "affected", "A slide blocks the road between Pa Nyit and Kan Pa Ni.", roles=["access"]),
             R(588, "affected", "Hills collapsed on the Kayin Gyi and Kan Pa Ni side; teams from Maungmagan are "
                                "working there."),
         ]),
    dict(id="shan-maw", mm="ရှမ်းမော်", en="Shan Maw", ts="Launglon", area="Launglon north-west",
         hazard="landslide", reports=[
             R(798, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),
    dict(id="kyone-ga-nan", mm="ကျုံဂဏန်း", en="Kyone Ga Nan", ts="Launglon", area="Launglon north-west",
         hazard="landslide", mimu_mm="ကျုံးဂဏန်း", match="variant",
         match_note="MIMU spells it ကျုံးဂဏန်း, in San Hlan village tract, 3 km south of Shan Maw.",
         reports=[
             R(798, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),
    dict(id="pein-ne-chaung", mm="ပိန္နဲချောင်း", en="Pein Ne Chaung", ts="Launglon", area="Launglon north-west",
         hazard="landslide", match="unlocated",
         match_note="MIMU's only Pein Hne Chaung is in Dawei Township, 25 km away across the river, not a village "
                    "reached through Pa Nyit.",
         reports=[
             R(798, "affected", "Reached only through Pa Nyit; cut off and out of contact since the road slides.",
               roles=["access", "comms"]),
         ]),

    # ================================================== Dawei
    dict(id="pyar-thar-chaung", mm="ပျားသားချောင်း", en="Pyar Thar Chaung", ts="Dawei", area="Dawei east",
         hazard="flood", reports=[
             R(501, "fatal", "Two children killed by a tree that fell as the flood ran strong.", dead=2),
         ]),

    # ================================================== Thayetchaung
    dict(id="kyauk-aing", mm="ကျောက်အိုင်", en="Kyauk Aing", ts="Thayetchaung", area="Thayetchaung",
         hazard="flood", reports=[
             R(571, "fatal", "A father and son swept away by the current; missing.", missing=2),
             R(499, "fatal", "Still missing on 29 Sep.", missing=2),
         ]),
    dict(id="mei-ke", mm="မယ်ကဲ", en="Mei Ke", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(572, "affected", "Two rope bridges destroyed.", roles=["access"])]),
    dict(id="ah-lel-su", mm="အလယ်စု", en="Ah Lel Su", ts="Thayetchaung", area="Thayetchaung", hazard="flood",
         reports=[R(475, "affected", "In the Taung Pyauk area. The water has fallen and the rain has stopped, a "
                                    "resident says.", roles=["receding"])]),
    *[dict(id=i, mm=mm, en=en, ts="Thayetchaung", area="Thayetchaung", hazard="flood", **kw,
           reports=[R(754, "affected", "Flooded near Thayetchaung town; phone lines are down, so there are no "
                                       "details.", roles=["comms"])])
      for i, mm, en, kw in [
          ("sin-ku", "ဆင်ကူး", "Sin Ku", {}),
          ("ya-nge", "ရငဲ", "Ya Nge", dict(mimu_mm="ရေငဲ (ရငဲ)", match="variant",
                                            match_note="MIMU lists it as ရေငဲ (ရငဲ), Yae Nge (Ya Nge).")),
          ("pi-taing", "ပိတိုင်", "Pi Taing", {}),
          ("min-dat", "မင်းဒပ်", "Min Dat", {}),
          ("son-sin-hpyar", "စုံစင်ဖျား", "Son Sin Hpyar", {}),
          ("pyin-hpyu-gyi", "ပြင်းဖြူကြီး", "Pyin Hpyu Gyi", {}),
      ]],

    # ================================================== Tanintharyi
    dict(id="thein-daw", mm="သိန္ဓော", en="Thein Daw tract", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt="Thein Daw",
         match_note="A village tract (MIMU: သိန်းဒေါ Thein Daw); shown at the tract's centre.",
         reports=[
             R(505, "affected", TNI_TRACTS),
             R(506, "affected", "Water rising faster than in the August flood; low roads and bridges under water, so "
                               "people travel by boat and raft.", roles=["access"]),
         ]),
    dict(id="ban-law", mm="ဘန်းလော", en="Ban Law", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         mimu_mm="ဘန်လော", vt_hint="Ban Law", match="variant",
         match_note="Named as a village tract; shown at MIMU's Ban Law village (ဘန်လော).",
         reports=[R(505, "affected", TNI_TRACTS)]),
    dict(id="maw-tone", mm="မော်တုန်း", en="Maw Tone tracts", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt=["Maw Tone (East)", "Maw Tone (West)"],
         match_note="MIMU splits Maw Tone (မော်တုံး) into East and West village tracts; shown at the centre of the "
                    "two.",
         reports=[R(505, "affected", TNI_TRACTS), R(508, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="pa-wa", mm="ပဝ", en="Pa Wa tract", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         match="approx", approx_vt="Pa Wa",
         match_note="A village tract with no village of that name in MIMU; shown at the tract's centre.",
         reports=[R(505, "affected", TNI_TRACTS), R(508, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="chaung-la-mu", mm="ချောင်းလမု", en="Chaung La Mu", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[R(505, "affected", TNI_TRACTS), R(508, "severe", TNI_LOW, depth_ft=6)]),
    dict(id="aw-gyi", mm="အော်ကြီး", en="Aw Gyi", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[R(485, "affected", "Travellers say the rising river is over the Myeik–Tanintharyi road here.",
                    roles=["access"])]),
    dict(id="u-yin-kwin", mm="ဥယျာဉ်ကွင်း", en="U Yin Kwin", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", mimu_mm="ဥယျာဉ်ကမ်း", match="probable",
         match_note="Taken as MIMU's U Yin Kan (ဥယျာဉ်ကမ်း), 3 km from Aw Gyi in the same tract; no U Yin Kwin in "
                    "MIMU.",
         reports=[R(485, "affected", "Travellers say the rising river is over the Myeik–Tanintharyi road here.",
                    roles=["access"])]),
    dict(id="lel-taung-yar", mm="လယ်တောင်ယာ", en="Lel Taung Yar", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[
             R(486, "affected", "About 5 ft of water on the Tanintharyi–Kawthoung road: vehicles cannot pass, and "
                               "motorcycles are ferried across on rafts.", depth_ft=5, roles=["access"]),
         ]),

    # ================================================== Bokpyin (Kawthoung District)
    dict(id="lay-hnya", mm="လေညှာ", en="Lay Hnya", ts="Bokpyin", area="Bokpyin", hazard="flood",
         mimu_mm="လေညာ", match="variant",
         match_note="MIMU spells it လေညာ (Lay Nyar), as the post itself does once; Htaung Yaik village tract.",
         reports=[
             R(611, "affected", "The Lay Hnya river rose into the village on 27 Sep: roads and low-lying houses under "
                                "water, and residents of the low ground moving up the pagoda hill. Knee-deep in the "
                                "village centre, with rain still falling on the evening of 28 Sep.", depth_ft=2),
         ]),
]

# ---------------------------------------------------------------------------
# 30 Sep update: the later 29 Sep posts (among them the afternoon round-up, lines
# 160-214) and the 30 Sep posts.
# ---------------------------------------------------------------------------
TKT8 = ("Among at least eight villages at the tip of the peninsula, Tha Kyet Taw and those beyond it, cut off by "
        "slides since 26 Sep; easy-to-cook food ran out from 27 Sep.")
KT4 = ("One of the four villages of Kyauk Twin tract (about 350 households) near Sin Htaung beach, cut off since the "
       "slides of 26 Sep.")
KT_NONE = "Five days on, no rescue has reached the tract and food is running short."
TNI_RU = "Among 20-odd villages in nine tracts along the Tanintharyi River under water (29 Sep round-up)."
WARDS_RU = "Flooded from the night of 27 Sep; the water fell on the morning of 29 Sep (29 Sep round-up)."

MORE30 = {
    # ---------------------------------------------- Launglon
    "launglon-town": [
        R(386, "affected", "The town and 37 villages of the township hit; 21 bodies recovered and tens missing (29 Sep "
                           "round-up)."),
        R(369, "affected", "Rescue teams from Mon and Kayin States camped at San Kin monastery on the evening of 29 Sep, "
                           "to start work in the township on 30 Sep.", roles=["relief"]),
    ],
    "ka-det-nge-htein": [
        R(387, "fatal", "The worst hit: ten bodies recovered and five people still missing. An advance team of a dozen "
                        "or so has been working here since 28 Sep.", dead=10, missing=5, rescue="reached"),
        R(388, "fatal", "Residents found three of the bodies, the rescuers the rest. The dead include children, a monk, "
                        "women and old people."),
        R(399, "fatal", "More than 30 houses destroyed, residents say."),
    ],
    "ka-det-gyi": [R(389, "fatal", "A mother and son killed when the hill fell on their orchard.", dead=2)],
    "nyaw-pyin": [
        R(390, "fatal", "The bodies of two women recovered, one of them a grandmother.", dead=2),
        R(399, "fatal", "More than 30 houses destroyed.", houses=30),
    ],
    "min-yat": [R(392, "fatal", "The body of a woman recovered.", dead=1)],
    "tha-byar": [
        R(393, "fatal", "A mother and son missing: the wife and son of Ko Aung Shein (Ko Aung Thar) of Kayin Gyi.",
          missing=2),
        R(401, "fatal", "Four houses completely destroyed and nearly 200 filled with silt; orchards buried.", houses=4),
        R(346, "fatal", "The village bridge on the Launglon–Dawei road is undermined by the hill stream and the slide: "
                        "the easternmost of its three concrete piers is about a third gone and the deck is split. Small "
                        "vehicles are told to keep to its west side, and lorries to go round by the Inn Zauk junction, "
                        "Way Di and Pyin Htein.", roles=["access"]),
        R(303, "fatal", "The bridge collapsed on the morning of 30 Sep. No vehicle can cross; all traffic, relief convoys "
                       "included, goes round by the Inn Zauk junction, Way Di and Pyin Htein.", roles=["access"]),
        R(306, "fatal", "More than 40 houses damaged, the bridge among them, and at least two people missing.",
          houses=40, missing=2),
        R(318, "fatal", "The Tanintharyi Region emergency team and partners came with seven vehicles and medical teams "
                        "to check and treat people, and to search for at least two bodies under the earth.",
          rescue="reached", roles=["relief"]),
        R(322, "fatal", "Slide earth covers about three football pitches west of the road; residents cannot go home "
                        "until it is cleared.", roles=["needs"]),
    ],
    "kyauk-ni-maw": [
        R(395, "fatal", "Eight residents missing. The slide hit the most crowded part of the village and destroyed about "
                        "50 houses (29 Sep round-up).", missing=8, houses=50),
        R(396, "fatal", "A resident on the night of 28 Sep: people cannot get from one neighbourhood to the next, and "
                        "no one has searched for the missing. More than 200 have moved to the monastery.",
          sheltering=200, rescue="not-reached", roles=["relief"]),
        R(272, "fatal", "The first village cut off by the slides, on 26 Sep. More than 50 houses went, and the wells and "
                       "ponds were wrecked.", houses=50),
        R(274, "fatal", "About 200 people trapped. The water stored at the monastery where they shelter is running low, "
                       "and they are drinking rainwater.", sheltering=200, roles=["relief", "needs"]),
        R(276, "fatal", "Rescuers reached Taw Kye on 30 Sep, but must get through the big slide at Za Lut first; a "
                       "villager expects about four more days.", rescue="not-reached", roles=["access"]),
        R(278, "fatal", "At least five people buried and missing, with no rescue possible more than five days on."),
        R(279, "fatal", "Villagers living elsewhere are arranging to bring food and medicine in by sea.",
          roles=["needs"]),
    ],
    "taw-kye": [
        R(397, "fatal", "Five dead, a Buddhist nun among them (29 Sep round-up).", dead=5),
        R(372, "fatal", "The blocked road was open as far as Taw Kye on the night of 29 Sep, a rescue group says.",
          rescue="reached"),
        R(275, "fatal", "Rescue teams coming down from Launglon reached Taw Kye on 30 Sep.", rescue="reached"),
        R(228, "fatal", "The teams are clearing the earth that blocks the road on to Tha Win.", roles=["access"]),
    ],
    "tha-win": [
        R(299, "affected", "One post says search-and-rescue teams had reached Tha Win; residents are clearing the slide "
                          "debris between here and Tha Kyet Taw.", roles=["access"]),
        R(228, "affected", "Rescue teams are clearing the earth blocking the road between Taw Kye and Tha Win.",
          roles=["access"]),
    ],
    "tha-kyet-taw": [
        R(293, "affected", "Cut off by slides since 26 Sep, with at least seven villages beyond it. Easy-to-cook food ran "
                          "out from 27 Sep; eggs, potatoes, onions, garlic and oil can no longer be bought.",
          roles=["access", "needs"]),
        R(300, "affected", "Residents are clearing the slide debris between Tha Win and Tha Kyet Taw.", roles=["access"]),
    ],
    "ra-be": [
        R(294, "affected", TKT8, roles=["access", "needs"]),
        R(311, "affected", "The track west into the hills to Kyauk Twin tract leaves the Launglon–Shin Maw road here."),
    ],
    "za-lut": [
        R(397, "fatal", "One dead (29 Sep round-up).", dead=1),
        R(276, "fatal", "A big slide here stands between the rescue teams and Kyauk Ni Maw.", roles=["access"],
          rescue="not-reached"),
    ],
    "za-lut-pyin-gyi": [
        R(294, "fatal", TKT8, roles=["access", "needs"]),
        R(221, "fatal", "U Tun Po, over 60, was swept away in a landslide on the night of 26 Sep; his body was found on "
                      "28 Sep, tangled in the wires of a fallen power pole."),
        R(223, "fatal", "Villagers dug out a man pinned by earth beside his house at about 8 pm on 26 Sep; on 30 Sep he "
                      "was handed to rescue teams and taken to Dawei General Hospital.", rescued=1),
        R(225, "fatal", "Ten houses near the five pagodas completely buried, and ten inside the village made unlivable by "
                      "silt.", houses=20),
        R(226, "fatal", "Road links cut since 26 Sep; clothes and food urgently needed.", roles=["access", "needs"]),
    ],
    "ti-zit": [
        R(402, "fatal", "Slides have closed the roads; once the village shops run out there will be nothing to eat "
                        "(29 Sep round-up).", roles=["access", "needs"]),
    ],
    "kayin-gyi": [
        R(360, "severe", "The hill stream ate away the main road by the bridge in the middle of the village and cut it "
                         "in two, severing the link to Kan Pa Ni; the upper village cannot bring food in.",
          roles=["access", "needs"]),
        R(363, "severe", "More than 80 houses destroyed by the hill stream and slides of 26–27 Sep. Residents shelter "
                         "together at the monastery and urgently need food and clothes.",
          houses=80, roles=["relief", "needs"]),
        R(232, "severe", "The road by the bridge below the village, about 10 ft of it gone since 27 Sep, was patched on "
                        "30 Sep by relief teams with a backhoe and dump trucks; food and emergency vehicles can now get "
                        "through to Kayin Gyi, Kan Pa Ni and Pa Nyit."),
        R(237, "severe", "Nearly 100 houses destroyed here and at Kan Pa Ni; hundreds of people are living in "
                        "monasteries.", roles=["relief"]),
        R(239, "severe", "The Tanintharyi Region emergency team and partners are giving relief and medical care.",
          rescue="reached"),
    ],
    "kan-pa-ni": [
        R(360, "affected", "Cut off from Kayin Gyi since the road by the Kayin Gyi bridge was washed out.",
          roles=["access"]),
        R(237, "severe", "Nearly 100 houses destroyed here and at Kayin Gyi; hundreds of people are living in "
                        "monasteries.", roles=["relief"]),
        R(238, "severe", "The Kan Pa Ni–Pa Nyit road is buried in about two places.", roles=["access"]),
        R(321, "severe", "The Tanintharyi Region emergency team and partners are going to help.", rescue="reached"),
    ],
    "pa-nyit": [R(238, "severe", "Two houses buried by a slide.", houses=2)],
    # ---------------------------------------------- Thayetchaung
    "thayetchaung-town": [
        R(252, "fatal", "Eight dead and 27 houses damaged in the township (29 Sep)."),
        R(254, "fatal", "Four houses destroyed in the town ward, on the Myeik–Dawei road between Nyaung Zin and Chauk "
                       "Chaung.", houses=4),
        R(259, "fatal", "From 27 Sep to midday on 28 Sep dozens of wards and villages were flooded up to the roofs."),
        R(262, "fatal", "Slides on the ridge west of the town's waterfall."),
        R(406, "fatal", "Flooded up to about 8 ft; the water has gone and people are clearing mud and broken trees "
                        "(29 Sep round-up).", depth_ft=8, roles=["receding"]),
        R(409, "fatal", "The town and more than 30 villages hit; six dead and two missing by the night of 28 Sep."),
    ],
    "saw-hpyar": [R(256, "fatal", "A couple killed.", dead=2)],
    "ka-nyin-chaung": [
        R(256, "fatal", "A couple killed.", dead=2),
        R(263, "fatal", "The Ka Nyin Chaung bridge has collapsed.", roles=["access"]),
        R(264, "fatal", "Relief teams cannot get past it to Pe Det; the Myat Parami charity is working to repair it.",
          roles=["access"]),
    ],
    "kyauk-aing": [
        R(257, "fatal", "The bodies of the father and son swept away by the current have been found.", dead=2, missing=0),
    ],
    "sin-ku": [
        R(254, "affected", "Three houses destroyed by the flood and slides.", houses=3),
        R(262, "affected", "A slide here cut the Myeik–Dawei road.", roles=["access"]),
        R(264, "affected", "The slide at Sin Ku, on the way out of Thayetchaung, has been cleared."),
    ],
    "kyauk-hlay-kar": [R(255, "affected", "One house damaged.", houses=1)],
    "ah-lel-su": [R(255, "affected", "One house damaged.", houses=1)],
    "mei-ke": [R(263, "affected", "Two rope bridges destroyed.", roles=["access"])],
    "pe-det": [
        R(261, "severe", "Houses flooded so deep that people had to climb onto their roofs (28 Sep)."),
        R(264, "severe", "Cut off: relief teams cannot get past the collapsed Ka Nyin Chaung bridge.",
          roles=["access", "needs"], rescue="not-reached"),
        R(268, "severe", "Residents need help to rebuild.", roles=["needs"]),
    ],
    "taung-pyauk": [
        R(260, "severe", "Villages flooded up to the roofs; some people trapped in their houses broke out through the "
                        "tin roofs."),
        R(258, "severe", "Houses deep in mud, which residents are washing out themselves.", roles=["receding"]),
        R(266, "severe", "Wells and ponds flooded: drinking water, food, clothes, blankets and mosquito nets are "
                        "urgently needed.", roles=["needs"]),
    ],
    "kyet-sar-pyin": [
        R(267, "affected", "A woman here: no relief group has come, neighbours share what they have, and with the wells "
                          "flooded, drinking water is the main need.", roles=["needs"]),
        R(408, "affected", "Residents sheltered together in houses the flood did not reach and on the hills.",
          roles=["relief"]),
    ],
    # ---------------------------------------------- Dawei
    "dawei-town": [
        R(352, "severe", "The water began falling on the morning of 29 Sep and had largely gone by evening. Six town "
                         "wards were flooded on 27–28 Sep and more than 600 people moved out.", roles=["receding"]),
        R(354, "severe", "Trees brought down by the strong winds still not cleared in places."),
        R(355, "severe", "Power back in some wards on the evening of 29 Sep; still off in others."),
    ],
    **{w: [R(414, "severe", WARDS_RU, roles=["receding"])]
       for w in ("shan-ma-le-swe-ward", "ka-nyon-ward", "ka-yat-pyin-ward", "bon-maw-ward", "khon-win-dat-ward",
                 "kyet-sa-pyin-ward")},
    "pauk-taing": [
        R(341, "affected", "With the water down on 30 Sep, the road on the right-hand side of the bridge, leaving Dawei, "
                           "is seen eaten away.", roles=["access"]),
    ],
    "pyar-thar-chaung": [R(416, "fatal", "Two children killed by a falling tree as the flood ran strong (Ban Chaung "
                                         "area).", dead=2)],
    # ---------------------------------------------- Tanintharyi
    "tanintharyi-town": [R(428, "affected", "Over 26 ft at about 3 pm on 29 Sep, more than 2 ft above the danger mark "
                                            "(29 Sep round-up).", river_ft=26)],
    "chaung-la-mu": [
        R(425, "severe", TNI_RU),
        R(242, "severe", "The water fell about 6 in on 30 Sep: lorries can pass again, passenger vehicles cannot.",
          roles=["receding", "access"]),
        R(244, "severe", "About 60 passenger vehicles still stranded in the tract.", roles=["access"]),
        R(247, "severe", "Nine places flooded on the Tanintharyi–Bokpyin road between Chaung La Mu and Yay Phyu; people "
                        "and motorcycles are ferried by boat.", roles=["access"]),
        R(249, "severe", "More than 300 households moved to higher ground as their houses went under.",
          roles=["relief"]),
    ],
    "ta-ku": [
        R(425, "affected", TNI_RU),
        R(283, "severe", "The river has been rising since 26 Sep; from 29 Sep houses went under and residents began "
                        "moving to higher ground.", roles=["relief"]),
        R(284, "severe", "Worse on 30 Sep, with no rain: houses by the river and on low ground are going under."),
        R(286, "severe", "The water is rising faster and higher than in the August flood."),
        R(288, "severe", "Tens of houses under water, some that stayed dry in earlier floods; two-storey houses flooded "
                        "downstairs."),
    ],
    **{k: [R(425, "affected", TNI_RU)] for k in ("thein-daw", "thar-ra-bwin", "ban-law", "maw-tone", "pa-wa",
                                                  "tha-kyet")},
}
_BY = {s["id"]: s for s in SITES}
for _k, _rs in MORE30.items():
    _BY[_k]["reports"].extend(_rs)
_BY["za-lut-pyin-gyi"]["match_note"] += (" The round-up's one death at Za Lut (line 397) is probably U Tun Po, reported "
                                         "here on 30 Sep; he is counted once, under Za Lut.")

SITES += [
    # ================================================== Launglon, the peninsula's tip
    dict(id="kyauk-pon", mm="ကျောက်ပုံ", en="Kyauk Pon", ts="Launglon", area="Launglon south", hazard="landslide",
         reports=[R(294, "affected", TKT8, roles=["access", "needs"])]),
    *[dict(id=i, mm=mm, en=en, ts="Launglon", area="Launglon south", hazard="landslide", **kw, reports=[
          R(294, "affected", TKT8, roles=["access", "needs"]),
          R(310, "affected", KT4, roles=["access"]),
          R(313, "affected", KT_NONE, rescue="not-reached", roles=["needs"]),
      ]) for i, mm, en, kw in [
          ("kyauk-twin", "ကျောက်တွင်း", "Kyauk Twin", {}),
          ("sun-gyi", "စွန်ကြီး", "Sun Gyi", {}),
          ("chaung-hpyar-gyi", "ချောင်းဖျားကြီး", "Chaung Hpyar Gyi", {}),
          ("wea-ma-kaik", "ဝဲမကိုက်", "Wea Ma Kaik", {}),
      ]],

    # ================================================== Thayetchaung
    *[dict(id=i, mm=mm, en=en, ts="Thayetchaung", area="Thayetchaung", hazard=hz,
           reports=[R(ln, "affected", tx, houses=n)])
      for i, mm, en, hz, ln, n, tx in [
          ("kywe-zat", "ကျွဲဇပ်", "Kywe Zat", "flood", 254, 2, "Two houses destroyed."),
          ("chauk-chaung", "ချောက်ချောင်း", "Chauk Chaung", "flood", 254, 1, "One house destroyed."),
          ("ka-zi-hte", "ကဇိထဲ", "Ka Zi Hte", "flood", 254, 2, "Two houses destroyed."),
          ("kywe-chan", "ကျွဲခြံ", "Kywe Chan", "flood", 255, 11,
           "Eleven houses damaged, the most of any village in the Taung Pyauk area."),
      ]],
    *[dict(id=i, mm=mm, en=en, ts="Thayetchaung", area="Thayetchaung", hazard="flood", match="unlocated",
           match_note="MIMU's only Pi Tauk villages are in Dawei, Myeik and Yebyu townships, far from Pe Det.",
           reports=[R(268, "affected", "Named with Pe Det: residents need help to rebuild.", roles=["needs"])])
      for i, mm, en in [("pi-tauk-gyi", "ပိတောက်ကြီး", "Pi Tauk Gyi"), ("pi-tauk-nge", "ပိတောက်ငယ်", "Pi Tauk Nge")]],

    # ================================================== Dawei, on the Pauk Taing stream
    *[dict(id=i, mm=mm, en=en, ts="Dawei", area="Dawei–Thayetchaung road", hazard="flood", reports=rs)
      for i, mm, en, rs in [
          ("kyauk-yat", "ကျောက်ရပ်", "Kyauk Yat",
           [R(339, "affected", "Flooded on 27 Sep when the Pauk Taing stream overflowed.")]),
          ("wa-maw", "ဝမော်", "Wa Maw",
           [R(339, "affected", "Flooded on 27 Sep when the Pauk Taing stream overflowed.")]),
          ("pauk-taing-village", "ပေါက်တိုင်း", "Pauk Taing village",
           [R(339, "affected", "Flooded on 27 Sep when the Pauk Taing stream overflowed."),
            R(340, "affected", "It floods every year, but this time the water rose higher and houses that had never "
                               "flooded went under.")]),
      ]],

    # ================================================== Tanintharyi
    dict(id="ban-pyayt", mm="ဘန်းပြည့်", en="Ban Pyae", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         vt_hint="Thein Daw", reports=[
             R(329, "severe", "The whole village is under water; residents have moved up a hill and need food.",
               roles=["relief", "needs"]),
             R(332, "severe", "They drink rainwater caught in buckets; there is nowhere to buy food and no one "
                              "supplying it. The food they brought is running out after three days.", roles=["needs"]),
             R(335, "severe", "About 100 households in East and West Ban Pyae; the water still rising on the night of "
                              "29 Sep. The worst of three floods this year."),
         ]),
    *[dict(id=i, mm=mm, en=en, ts="Tanintharyi", area="Tanintharyi", hazard="flood", vt_hint="Ta Ku", reports=rs)
      for i, mm, en, rs in [
          ("inn-shey-kone", "အင်းရှည်ကုန်း", "Inn Shey Kone", [R(290, "severe", "Houses under water; more people "
                                                                        "moving out here than elsewhere in the tract.",
                                                                        roles=["relief"])]),
          ("ywar-ma", "ရွာမ", "Ywar Ma", [R(290, "severe", "Houses under water; more people moving out here than "
                                                          "elsewhere in the tract.", roles=["relief"])]),
          ("kyauk-sa-yit", "ကျောက်စရစ်", "Kyauk Sa Yit",
           [R(289, "affected", "Every road under water; boats only.", roles=["access"]),
            R(290, "severe", "Houses under water; more people moving out here than elsewhere in the tract.",
              roles=["relief"])]),
          ("ta-ku-nge", "တကူငယ်", "Ta Ku Nge", [R(290, "severe", "Houses under water; more people moving out here "
                                                                "than elsewhere in the tract.", roles=["relief"])]),
          ("wan-nar", "ဝမ်းနာ", "Wan Nar", [R(290, "severe", "Houses under water; more people moving out here than "
                                                            "elsewhere in the tract.", roles=["relief"])]),
          ("taik-kan", "တိုက်ကမ်း", "Taik Kan", [R(289, "affected", "Every road under water; boats only.",
                                                    roles=["access"])]),
          ("mya-yar-chaung", "မြရာချောင်း", "Mya Yar Chaung", [R(289, "affected", "Every road under water; boats only.",
                                                                  roles=["access"])]),
          ("koe-inn", "ကိုးအင်း", "Koe Inn", [R(289, "affected", "Every road under water; boats only.",
                                                 roles=["access"])]),
      ]],
    dict(id="pyi-aye", mm="ပြည်အေး", en="Pyi Aye", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         match="unlocated", match_note="Named as one of Ta Ku tract's 14 villages; not in MIMU village points.",
         reports=[R(290, "severe", "Houses under water; more people moving out here than elsewhere in the tract.",
                    roles=["relief"])]),
    dict(id="yae-hpyu-tni", mm="ရေဖြူ", en="Yay Phyu", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[
             R(245, "affected", "The road between Yay Phyu and Ta Pa Lat is still hard to get through.",
               roles=["access"]),
             R(247, "affected", "Northern end of the nine flooded stretches of the Tanintharyi–Bokpyin road from Chaung "
                               "La Mu.", roles=["access"]),
         ]),
    dict(id="ta-pa-lat", mm="တားပလပ်", en="Ta Pa Lat", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         mimu_mm="တပလပ်", match="variant", match_note="MIMU spells it တပလပ် (Ta Pa Lat), in Chaung La Mu tract.",
         reports=[R(245, "affected", "The road between Yay Phyu and Ta Pa Lat is still hard to get through.",
                    roles=["access"])]),
]

# Places the posts use only as reference points
REFERENCES = [
    dict(id="shin-maw", mm="ရှင်မော်", en="Shin Maw", line=978,
         note="Southern end of the affected stretch of the Launglon peninsula, home to one of the 'nine "
              "Shins' pagodas. Not in MIMU village points, so not mapped."),
    dict(id="htee-khee", mm="ထီးခီး", en="Htee Khee", line=857,
         note="Thai–Myanmar border crossing at the far end of the Dawei–Htee Khee road."),
    dict(id="sez", mm="ထားဝယ် အထူးစီးပွားရေးဇုန်", en="Dawei SEZ deep-sea port", line=1129,
         note="Its condition was still being checked on 27 Sep."),
]

# Incidents that are not a village. `at` = a site's position; `between` = midpoint
# of two sites, moved onto the nearest MIMU road.
INCIDENTS = [
    dict(id="poe-zar-pin", kind="road-block", en="Poe Zar Pin landslide", mm="ပိုးစာပင်တောင်ပြို",
         between=["launglon-town", "nyin-maw"], line=961, day=27,
         text="The hill between Launglon town and Nyin Maw collapsed on the morning of 27 Sep, burying the "
              "road in earth, rock and trees. It stopped the rescue convoy at about 2:30 pm; the alternative "
              "route by Pyin Htein was under water a person's height deep.",
         match_note="Hill not in MIMU. Placed midway between Launglon town and Nyin Maw, then moved onto the "
                    "nearest MIMU road."),
    dict(id="pyin-htein-route", kind="flooded-road", en="Pyin Htein route under water", mm="ပြင်းထိန်ရွာလမ်း",
         at="pyin-htein", line=963, day=27,
         text="The detour around the Poe Zar Pin slide through Pyin Htein was under water about a person's "
              "height deep."),
    dict(id="ka-myaw-gyi-road", kind="flooded-road", en="Road closed at Ka Myaw Gyi", mm="ကမြောကြီး",
         at="ka-myaw-gyi", line=1106, day=27,
         text="Vehicles barred from Ka Myaw Gyi, at the Dawei–Launglon boundary, onward; flooding held up "
              "rescue teams there on the morning of 27 Sep."),
    dict(id="shin-maw-road", kind="road-cut", en="Road to Shin Maw destroyed", mm="ကျောက်နီမော်–ရှင်မော်လမ်း",
         at="kyauk-ni-maw", line=1097, day=27,
         text="The road from Kyauk Ni Maw to Shin Maw is destroyed and impassable."),
    dict(id="kayin-gyi-bridge", kind="bridge-out", en="Kayin Gyi bridge and roads destroyed", mm="ကရင်ကြီး တံတား",
         at="kayin-gyi", line=848, day=28,
         text="The second slide destroyed the village bridge and roads; the road by the bridge is cut. On 30 Sep relief teams patched the road by the bridge with a backhoe and dump trucks, so food and emergency vehicles can get through (line 234)."),
    dict(id="san-chi-bridge", kind="bridge-flood", en="San Chi bridge submerged", mm="ဆန်းချီတံတား",
         at="san-chi", line=1012, day=27,
         text="Water over the San Chi bridge on 27 Sep; submerged by 28 Sep."),
    dict(id="pa-kar-ri-road", kind="road-cut", en="Dawei–Htee Khee road impassable", mm="ထားဝယ်-ထီးခီးလမ်း",
         at="pa-kar-ri", line=867, day=28,
         text="With Pa Kar Ri under water, vehicles cannot pass on the Dawei–Htee Khee border road."),
    dict(id="tha-yet-ngoke-slide", kind="road-slide", en="Slide on the road near Tha Yet Ngoke", mm="သရက်ငုတ်",
         at="tha-yet-ngoke", line=866, day=28,
         text="A landslide on the main road leaves one lane; vehicles pass one at a time."),
    dict(id="ka-nyin-chaung-bridge", kind="bridge-out", en="Ka Nyin Chaung bridge destroyed",
         mm="ကညင်ချောင်း တံတား", at="ka-nyin-chaung", line=913, day=28,
         text="The bridge on Union Road No. 8 at Ka Nyin Chaung was destroyed, cutting the Dawei–Myeik road."),
    dict(id="thin-kyun-road", kind="flooded-road", en="Dawei–Myeik road flooded", mm="ထားဝယ်-မြိတ်လမ်း",
         at="thin-kyun", line=1028, day=27,
         text="2–4 ft of water on the road on 27 Sep: vehicles from Dawei turned back at Thin Kyun, vehicles "
              "from Myeik were stranded near Pe Det and beyond Palauk. By 28 Sep some stretches were 6–8 ft "
              "deep."),
    dict(id="tha-ra-bwin-bridge", kind="bridge-flood", en="Thar Ra Bwin bridge submerged", mm="သာရဘွင် တံတား",
         at="thar-ra-bwin", line=841, day=28,
         text="The bridge linking Thar Ra Bwin and the east-bank village is under water."),
    # ---- 29 Sep update
    dict(id="pa-nyit-road-e", kind="road-slide", en="Slide on the road to Pa Nyit", mm="လောင်းလုံး–ပညစ်လမ်း",
         between=["launglon-town", "pa-nyit"], line=797, day=28,
         text="Photos show a slide across the road between Launglon town and Pa Nyit.",
         match_note="Placed midway between Launglon town and Pa Nyit, then moved onto the nearest MIMU road."),
    dict(id="pa-nyit-road-n", kind="road-slide", en="Slide on the road to Kan Pa Ni", mm="ပညစ်–ကမ်းပနီလမ်း",
         between=["pa-nyit", "kan-pa-ni"], line=797, day=28,
         text="A second slide between Pa Nyit and Kan Pa Ni. Shan Maw, Pein Ne Chaung and Kyone Ga Nan, reached "
              "through Pa Nyit, are cut off.",
         match_note="Placed midway between Pa Nyit and Kan Pa Ni, then moved onto the nearest MIMU road."),
    dict(id="za-lun-road", kind="flooded-road", en="Road near Za Lun impassable", mm="ဗျောတောဝ–ဇလွန်းလမ်း",
         at="za-lun", line=714, day=28,
         text="Cars and motorcycles could not get through between Byaw Taw Wa and Za Lun, east of Dawei, on the "
              "evening of 28 Sep."),
    dict(id="mei-ke-bridges", kind="bridge-out", en="Two rope bridges destroyed at Mei Ke", mm="မယ်ကဲ ကြိုးတံတား",
         at="mei-ke", line=572, day=28, text="Two rope bridges at Mei Ke, Thayetchaung, were destroyed."),
    dict(id="ti-zit-road", kind="road-block", en="Slide debris between Nyin Maw and Ti Zit", mm="ညင်းမော်–တီဇစ်လမ်း",
         between=["nyin-maw", "ti-zit"], line=444, day=29,
         text="Earth and rock from the slides of 26 Sep block the hill road from Nyin Maw over to Ti Zit; residents "
              "want it cleared so the village can be reached.",
         match_note="Placed midway between Nyin Maw and Ti Zit, then moved onto the nearest MIMU road."),
    dict(id="shin-maw-bridges", kind="bridge-out", en="Bridges down on the road to Shin Maw", mm="ရှင်မော်လမ်း တံတားများ",
         at="kyauk-wut-pyin", line=465, day=29,
         text="Many bridges are destroyed on the road from Kyauk Ni Maw down to Shin Maw.",
         match_note="Placed at Kyauk Wut Pyin, on that road; the posts do not say which bridges."),
    dict(id="aw-gyi-road", kind="flooded-road", en="Myeik–Tanintharyi road under water", mm="မြိတ်-တနင်္သာရီလမ်း",
         at="aw-gyi", line=485, day=29,
         text="The rising river is over the road at Aw Gyi and U Yin Kwin, travellers say."),
    dict(id="lel-taung-yar-road", kind="flooded-road", en="Tanintharyi–Kawthoung road 5 ft under",
         mm="တနင်္သာရီ-ကော့သောင်းလမ်း", at="lel-taung-yar", line=486, day=29,
         text="About 5 ft of water on the road at Lel Taung Yar; vehicles cannot pass and motorcycles cross on rafts."),
    # ---- 30 Sep update
    dict(id="tha-byar-bridge", kind="bridge-out", en="Tha Byar bridge collapses", mm="သဗျာရွာတံတား",
         at="tha-byar", line=303, day=30,
         text="Undermined on 29 Sep, the bridge on the Dawei–Launglon road at Tha Byar collapsed on the morning of "
              "30 Sep. Traffic to Launglon goes round by the Inn Zauk junction, Way Di and Pyin Htein.",
         match_note="Placed at Tha Byar village; MIMU has no point for this bridge."),
    dict(id="sin-ku-slide", kind="road-slide", en="Slide on the Myeik–Dawei road at Sin Ku", mm="ဆင်ကူး",
         at="sin-ku", line=262, day=29,
         text="A slide at Sin Ku, on the way out of Thayetchaung, cut the Myeik–Dawei road; it has since been cleared."),
    dict(id="bok-taung-slide", kind="road-block", en="Slide at Bok Taung blocks the Myeik–Dawei road",
         mm="ဘုတ်တောင်", between=["pe-det", "palauk"], line=342, day=29,
         text="Slides on 27–28 Sep brought Bok Taung down onto the Myeik–Dawei road; still impassable on 30 Sep, "
              "residents of Myeik say.",
         match_note="Bok Taung is not in MIMU. Placed midway between Pe Det and Palauk, where the posts put its foot, "
                    "then moved onto the nearest MIMU road."),
    dict(id="pauk-taing-road", kind="road-cut", en="Road by the Pauk Taing bridge eaten away", mm="ပေါက်တိုင်းတံတား",
         at="pauk-taing", line=341, day=30,
         text="With the water down on 30 Sep, the Dawei–Myeik road beside the Pauk Taing bridge, on the right leaving "
              "Dawei, is seen eaten away."),
    dict(id="tha-win-road", kind="road-block", en="Slide between Taw Kye and Tha Win", mm="တောကျဲ–သဝင်လမ်း",
         between=["taw-kye", "tha-win"], line=228, day=30,
         text="Rescue teams are clearing the earth that blocks the road from Taw Kye on to Tha Win.",
         match_note="Placed midway between Taw Kye and Tha Win, then moved onto the nearest MIMU road."),
    dict(id="za-lut-slide", kind="road-block", en="Big slide at Za Lut", mm="ဇလွတ်",
         at="za-lut", line=276, day=30,
         text="A big slide at Za Lut stands between the rescue teams and Kyauk Ni Maw; a villager expects about four "
              "more days' work to get through."),
    dict(id="kyauk-twin-road", kind="road-block", en="Launglon–Shin Maw road buried", mm="လောင်းလုံး-ရှင်မော်လမ်း",
         between=["ra-be", "kyauk-twin"], line=312, day=30,
         text="Slide earth covers most of the Launglon–Shin Maw road, and the track from Ra Be west into the hills to "
              "Kyauk Twin tract is closed.",
         match_note="Placed midway between Ra Be and Kyauk Twin, then moved onto the nearest MIMU road."),
    dict(id="chaung-la-mu-road", kind="flooded-road", en="Tanintharyi–Bokpyin road under water in nine places",
         mm="တနင်္သာရီ-ဘုတ်ပြင်းလမ်း", at="chaung-la-mu", line=247, day=30,
         text="Nine stretches under water between Chaung La Mu and Yay Phyu; people and motorcycles go by boat. "
              "Lorries were moving again by 3 pm on 30 Sep; about 60 passenger vehicles were still stranded."),
    dict(id="ta-ku-roads", kind="flooded-road", en="Roads and bridges under water in Ta Ku tract", mm="တကူ",
         at="ta-ku", line=287, day=30,
         text="Roads and bridges under water; motorcycles are ferried on boats and rafts, and at Kyauk Sa Yit, Taik "
              "Kan, Mya Yar Chaung and Koe Inn boats are the only way to get about."),
    # military movements the posts report alongside the disaster
    dict(id="kyauk-sin-troops", kind="troops", en="Junta troops at Kyauk Sin", mm="ကျောက်ဆင်",
         at="kyauk-sin", line=649, day=28,
         text="About 100 junta troops entered Kyauk Sin village tract, which includes landslide-hit Kayin Gyi. They "
              "said they had come to help but stayed at Kyauk Sin, and residents fled."),
    dict(id="sez-troops", kind="troops", en="Junta column in the Dawei SEZ", mm="ရလိုင်၊ ပုဂေါဇွန်း၊ သစ်တို့ထောင့်",
         at="ya-laing", line=679, day=28,
         text="A column of about 300 has been in Ya Laing, Pu Gaw Zun and Thit Toe Htaung, in the Dawei Special "
              "Economic Zone, since 23 Sep, after a clash near Pein Shaung on 25 Sep. Residents fled into the storm. "
              "Resistance forces say they have pulled back to avoid fighting during the disaster.",
         match_note="Placed at Ya Laing, the first of the three villages named."),
    dict(id="sez-clash", kind="troops", en="Fighting in the Dawei SEZ", mm="သစ်တိုထောင့်–ရလိုင်",
         between=["thit-to-htaunt", "ya-laing"], line=419, day=29,
         text="On the morning of 29 Sep junta and resistance forces fought west of the road between Thit Toe Htaung and "
              "Ya Laing, in the Dawei Special Economic Zone, Yebyu Township. Residents report heavy and small arms fire "
              "into the village, and firing still at 3 pm; people fled.",
         match_note="Placed midway between Thit Toe Htaung and Ya Laing, then moved onto the nearest MIMU road."),
]

# The rescue convoy's progress. `at` = site or incident id; `mode` = how the leg into
# this point was travelled.
RESCUE = [
    dict(at="dawei-town", day=27, t="27 Sep, early morning", line=979, mode="road",
         en="Emergency rescue teams leave Dawei for Launglon."),
    dict(at="ka-myaw-gyi", day=27, t="27 Sep, to 9:30 am", line=1147, mode="road", stop=True,
         en="Held up by flooding at Ka Myaw Gyi; the red-level villages are out of reach."),
    dict(at="tha-byar", day=27, t="27 Sep, ~11 am", line=1055, mode="road",
         en="Reach Tha Byar and clear slide debris from the road near Pyin Sa Thi Maw and the monastery."),
    dict(at="launglon-town", day=27, t="27 Sep, midday", line=960, mode="road",
         en="Reach Launglon town."),
    dict(at="poe-zar-pin", day=27, t="27 Sep, 2:30–4:30 pm", line=962, mode="road", stop=True,
         en="Stopped by the Poe Zar Pin slide. The detour is flooded; the teams appeal for backhoes and "
            "tractors to dig through."),
    dict(at="ka-det-nge-htein", day=28, t="28 Sep, ~8 am", line=828, mode="foot",
         en="An advance team walks round the slide on forest paths and reaches Kadet Nge Htein; search and "
            "rescue begins."),
    dict(at="auk-yay-phyu", day=28, t="28 Sep", line=820, mode="foot", stop=True,
         en="Furthest point reached. Villages further south, Taw Kye, Tha Kyet Taw, Ra Be, Za Lut and Nyaw "
            "Pyin, have had no help."),
    # `frm`: the leg into this point starts there, not at the previous entry
    dict(at="nyin-maw", frm="poe-zar-pin", day=29, t="29 Sep", line=461, mode="road",
         en="Backhoes have cleared the road as far as Nyin Maw, the teams' base and supply point since 28 Sep. "
            "Kyauk Ni Maw and the villages beyond still have no rescue team."),
    dict(at="taw-kye", day=29, t="29 Sep, night", line=372, mode="road",
         en="The blocked road is open as far as Taw Kye, a rescue group says."),
    dict(at="tha-win-road", day=30, t="30 Sep", line=275, mode="road", stop=True,
         en="Teams reach Taw Kye and dig at the slide on the road to Tha Win. The big slide at Za Lut still stands "
            "between them and Kyauk Ni Maw, perhaps four more days' work."),
]

# `t` orders events and places them on the rain chart; `when` is what the text says.
TIMELINE = [
    dict(t="2026-09-25T18:00", when="25 Sep, evening", area="Launglon", line=1092, kind="landslide",
         site="kyet-hlut", en="Hills in southern Launglon begin collapsing, as far as Kyet Lut."),
    dict(t="2026-09-26T08:00", when="26 Sep, morning", area="Launglon", line=1157, kind="rain",
         en="Heavy rain sets in over Launglon and keeps falling into the night."),
    dict(t="2026-09-26T17:00", when="26 Sep, ~5 pm", area="Launglon", line=1095, kind="landslide",
         site="kyauk-ni-maw", en="A landslide buries houses and people at Kyauk Ni Maw."),
    dict(t="2026-09-26T17:30", when="26 Sep, ~5 pm", area="Launglon", line=1159, kind="access",
         en="People push motorcycles through floodwater on tractors; by night every road is under water and "
            "the bridges are submerged."),
    dict(t="2026-09-26T18:00", when="26 Sep, 6 pm", area="Launglon", line=1178, kind="rescue",
         site="kyauk-ni-maw", en="Villagers pull an elderly person and two children from the slide at Kyauk Ni "
                                 "Maw; the ground is still moving."),
    dict(t="2026-09-26T21:00", when="26 Sep, ~9 pm", area="Launglon", line=1046, kind="landslide",
         site="kayin-gyi", en="First slide at Kayin Gyi."),
    dict(t="2026-09-26T22:00", when="26 Sep, night", area="Launglon", line=1160, kind="flood",
         en="Families in low-lying Launglon homes move out in the dark."),
    dict(t="2026-09-27T00:00", when="27 Sep, ~midnight", area="Thayetchaung", line=1067, kind="flood",
         site="kin-shey", en="Water starts entering houses in Kin Shey; by dawn the ground floors are under."),
    dict(t="2026-09-27T02:00", when="27 Sep, ~2 am", area="Launglon", line=1046, kind="landslide",
         site="kayin-gyi", en="Second slide at Kayin Gyi; nearly 30 houses buried."),
    dict(t="2026-09-27T07:00", when="27 Sep, morning", area="Dawei", line=933, kind="flood",
         site="dawei-town", en="Water starts entering wards of Dawei town."),
    dict(t="2026-09-27T08:00", when="27 Sep, morning", area="Dawei", line=860, kind="flood",
         site="pa-kar-ri", en="Water enters Pa Kar Ri on the border road; residents start moving out."),
    dict(t="2026-09-27T08:30", when="27 Sep, morning", area="Thayetchaung", line=949, kind="flood",
         site="taung-pyauk", en="Floods begin in the Taung Pyauk area."),
    dict(t="2026-09-27T09:30", when="27 Sep, 9:30 am", area="Launglon", line=1150, kind="access",
         site="ka-myaw-gyi", en="Rescue teams are held at Ka Myaw Gyi by floodwater; four red-level villages "
                                "are out of reach."),
    dict(t="2026-09-27T10:00", when="27 Sep, morning", area="Launglon", line=961, kind="landslide",
         site="poe-zar-pin", en="Poe Zar Pin hill collapses onto the road between Launglon and Nyin Maw."),
    dict(t="2026-09-27T11:00", when="27 Sep, ~11 am", area="Launglon", line=1055, kind="rescue",
         site="tha-byar", en="Rescue teams reach Tha Byar and clear slide debris."),
    dict(t="2026-09-27T12:00", when="27 Sep, 12 noon", area="Launglon", line=1061, kind="toll",
         en="Three bodies recovered in Launglon; tens missing. Slides continue on the western hills."),
    dict(t="2026-09-27T12:30", when="27 Sep, midday", area="Launglon", line=1078, kind="toll",
         site="min-yat", en="Mother's body recovered at Min Yat; her child is found alive."),
    dict(t="2026-09-27T13:00", when="27 Sep, midday", area="Launglon", line=984, kind="comms",
         site="kyauk-ni-maw", en="Contact with Kyauk Ni Maw is lost."),
    dict(t="2026-09-27T14:30", when="27 Sep, ~2:30 pm", area="Launglon", line=979, kind="access",
         site="poe-zar-pin", en="The Poe Zar Pin slide stops the rescue convoy heading south."),
    dict(t="2026-09-27T15:00", when="27 Sep, 3 pm", area="District", line=1021, kind="rain",
         en="Strong winds sweep Dawei District; the rain does not let up."),
    dict(t="2026-09-27T15:30", when="27 Sep, 3:30 pm", area="Thayetchaung", line=1029, kind="flood",
         site="thin-kyun", en="Water on the Dawei–Myeik road at Thin Kyun drops by about 2 ft."),
    dict(t="2026-09-27T16:30", when="27 Sep, 4:30 pm", area="Launglon", line=962, kind="access",
         site="poe-zar-pin", en="Rescue teams still stuck at the slide; they appeal for backhoes and tractors."),
    dict(t="2026-09-27T18:00", when="27 Sep", area="Dawei", line=941, kind="rain",
         en="DMH: 11.02 in (280 mm) of rain at Dawei, the highest on record. The old record, 9.68 in, dated "
            "from 1998."),
    dict(t="2026-09-27T19:00", when="27 Sep, evening", area="Dawei", line=936, kind="rescue",
         site="ka-nyon-ward", en="Ten people, including elderly people and a child, rescued from rising water "
                                 "near Taik Thit monastery. Power is cut to the whole town."),
    dict(t="2026-09-27T19:30", when="27 Sep, evening", area="Tanintharyi", line=844, kind="comms",
         site="tanintharyi-town", en="Phone and internet lines go down across Tanintharyi Township."),
    dict(t="2026-09-27T21:00", when="27 Sep, night", area="Launglon", line=847, kind="landslide",
         site="kayin-gyi", en="Another slide buries the whole eastern half of Kayin Gyi."),
    dict(t="2026-09-27T21:30", when="27 Sep, night", area="Dawei", line=862, kind="flood",
         site="pa-kar-ri", en="Low-lying houses in Pa Kar Ri are completely submerged."),
    dict(t="2026-09-27T22:00", when="27 Sep", area="Launglon", line=817, kind="toll", site="nyaw-pyin",
         approx=True, en="A landslide at Nyaw Pyin kills two women (reported on 28 Sep)."),
    dict(t="2026-09-28T05:30", when="28 Sep, early morning", area="Launglon", line=827, kind="rescue",
         site="poe-zar-pin", en="An advance rescue team leaves the road and walks round the slide through "
                                "the forest."),
    dict(t="2026-09-28T07:00", when="28 Sep, morning", area="Dawei", line=920, kind="flood",
         site="bon-maw-ward", en="Single-storey houses under water in five Dawei wards."),
    dict(t="2026-09-28T08:00", when="28 Sep, ~8 am", area="Launglon", line=828, kind="rescue",
         site="ka-det-nge-htein", en="The advance team reaches Kadet Nge Htein and starts searching."),
    dict(t="2026-09-28T09:00", when="28 Sep, morning", area="Region", line=928, kind="forecast",
         en="DMH: the low off the Tanintharyi coast may become a depression within 24 hours, moving north "
            "and north-west towards the Ayeyarwady delta."),
    dict(t="2026-09-28T09:30", when="28 Sep, morning", area="Launglon", line=822, kind="comms",
         site="nyaw-pyin", en="No contact with Nyaw Pyin: phone and internet are down."),
    dict(t="2026-09-28T10:00", when="28 Sep, morning", area="Launglon", line=853, kind="toll",
         en="At least five bodies recovered in Launglon; dozens still missing. Rescuers have not reached "
            "Kadet Nge [Htein], Ti Zit or Za Lut."),
    dict(t="2026-09-28T11:00", when="28 Sep", area="Thayetchaung", line=913, kind="access",
         site="ka-nyin-chaung", approx=True,
         en="The Ka Nyin Chaung bridge on Union Road No. 8 is destroyed; the Dawei–Myeik road is cut."),
    dict(t="2026-09-28T12:00", when="28 Sep, 12 noon", area="Launglon", line=830, kind="access",
         site="poe-zar-pin", en="The rest of the rescue force is still clearing earth from the Launglon–Nyin "
                                "Maw road."),
    dict(t="2026-09-28T12:30", when="28 Sep", area="Tanintharyi", line=838, kind="flood", site="tha-kyet",
         approx=True, en="After three days of rain, villages on the Tanintharyi River begin to flood."),
    dict(t="2026-09-28T13:00", when="28 Sep", area="Launglon", line=820, kind="access", site="auk-yay-phyu",
         approx=True, en="The rescue team has got no further than Auk Yay Phyu; villages to the south have "
                         "had no help."),
    # ---- 29 Sep update
    dict(t="2026-09-26T19:30", when="26 Sep, night", area="Launglon", line=694, kind="toll",
         site="ka-det-nge-htein", approx=True, en="Thirteen people go missing in the Kadet Nge Htein slide."),
    dict(t="2026-09-26T20:00", when="26 Sep", area="Launglon", line=530, kind="landslide", site="nyaw-pyin",
         approx=True, en="At Nyaw Pyin the hill 'roars like an aeroplane', then collapses; neighbours dig out an "
                         "old woman. (A 28 Sep post dates the deaths here to 27 Sep.)"),
    dict(t="2026-09-26T20:30", when="26 Sep, night", area="Launglon", line=442, kind="landslide", site="ti-zit",
         approx=True, en="Hills round Ti Zit collapse, burying the village's streets and the hill road out."),
    dict(t="2026-09-26T21:00", when="26 Sep, ~9 pm", area="Launglon", line=805, kind="flood", site="way-di",
         en="Water starts rising at Way Di; the road to Kone Zayat goes nearly 5 ft under and about 20 cattle "
            "are swept away."),
    dict(t="2026-09-26T22:30", when="26 Sep, night", area="Launglon", line=516, kind="landslide", site="thea-pon",
         approx=True, en="Inwa hill slides onto the monastery at Thea Pon."),
    dict(t="2026-09-27T15:00", when="27 Sep", area="Launglon", line=795, kind="landslide", site="pa-nyit",
         approx=True, en="Slides at Pa Nyit bury two houses and cut the road either side of the village."),
    dict(t="2026-09-27T16:00", when="27 Sep, ~4 pm", area="Dawei", line=713, kind="comms", site="dawei-town",
         en="Electricity is cut across the district's flooded areas."),
    dict(t="2026-09-27T22:00", when="27 Sep, night", area="Dawei", line=707, kind="rescue", site="ka-nyon-ward",
         en="Residents of seven Dawei wards are moved out overnight to monasteries."),
    dict(t="2026-09-28T12:00", when="28 Sep, from midday", area="District", line=789, kind="rain",
         en="Rain stops over Dawei, Launglon and most other places; the water starts to fall."),
    dict(t="2026-09-28T14:00", when="28 Sep, afternoon", area="Launglon", line=696, kind="toll",
         site="ka-det-nge-htein", en="The Zambu Thiri team recovers the bodies of a 12-year-old boy and a monk; five "
                                     "dead at Kadet Nge Htein."),
    dict(t="2026-09-28T15:00", when="28 Sep, afternoon", area="Thayetchaung", line=468, kind="recede",
         site="thayetchaung-town", en="Water falls in Thayetchaung; the clean-up of mud and fallen trees begins."),
    dict(t="2026-09-28T16:00", when="28 Sep", area="Launglon", line=814, kind="toll",
         en="Dawei Watch's Launglon count reaches nine dead; dozens missing."),
    dict(t="2026-09-28T17:00", when="28 Sep, evening", area="Launglon", line=717, kind="toll", site="ka-det-gyi",
         en="The bodies of a mother and son are found under slide earth in their orchard at Kadet Gyi."),
    dict(t="2026-09-28T18:00", when="28 Sep, evening", area="Launglon", line=802, kind="recede",
         site="launglon-town", en="Water falls in Launglon town, Ka Myaw Gyi, Way Di, Min Yat and Tha Byar."),
    dict(t="2026-09-28T18:30", when="28 Sep", area="Dawei", line=783, kind="rain",
         en="DMH: 13.62 in (346 mm) of rain at Dawei, beating the day-old record."),
    dict(t="2026-09-28T19:00", when="28 Sep, evening", area="Thayetchaung", line=568, kind="toll",
         en="Six dead in Thayetchaung Township and two swept away."),
    dict(t="2026-09-28T19:30", when="28 Sep, evening", area="Launglon", line=702, kind="toll",
         en="The Launglon count reaches twelve dead."),
    dict(t="2026-09-29T07:00", when="29 Sep, morning", area="Dawei", line=541, kind="recede", site="bon-maw-ward",
         en="Water falls in Dawei's wards; the sun comes out and people go home to clean up."),
    dict(t="2026-09-29T09:00", when="29 Sep, morning", area="Launglon", line=550, kind="toll", site="tha-byar",
         en="A mother and son at Tha Byar are still missing after three days."),
    dict(t="2026-09-29T10:00", when="29 Sep", area="Launglon", line=461, kind="rescue", site="nyin-maw",
         approx=True, en="Backhoes have cleared the road as far as Nyin Maw; Kyauk Ni Maw is days away."),
    dict(t="2026-09-29T12:00", when="29 Sep, midday", area="District", line=490, kind="toll",
         en="Dawei Watch counts 23 dead in three townships (15 in Launglon, 6 in Thayetchaung, 2 in Dawei), with "
            "dozens missing."),
    dict(t="2026-09-29T12:30", when="29 Sep, midday", area="Dawei", line=545, kind="comms", site="dawei-town",
         en="Dawei town has now had no electricity since 27 Sep."),
    dict(t="2026-09-29T15:00", when="29 Sep, ~3 pm", area="Tanintharyi", line=480, kind="flood",
         site="tanintharyi-town", en="The Tanintharyi River passes 26 ft, over 2 ft above its 24 ft danger mark."),
    dict(t="2026-09-29T16:00", when="29 Sep", area="Tanintharyi", line=486, kind="access", site="lel-taung-yar",
         approx=True, en="5 ft of water on the Tanintharyi–Kawthoung road; motorcycles cross on rafts."),
    # ---- 30 Sep update
    dict(t="2026-09-26T20:00", when="26 Sep, ~8 pm", area="Launglon", line=223, kind="landslide",
         site="za-lut-pyin-gyi", en="A slide at Za Lut Pyin Gyi sweeps away U Tun Po; villagers dig out a man pinned "
                                    "by the earth."),
    dict(t="2026-09-29T09:00", when="29 Sep, morning", area="Yebyu", line=419, kind="conflict", site="sez-clash",
         en="Fighting breaks out in the Dawei SEZ between junta and resistance forces; residents flee."),
    dict(t="2026-09-29T11:00", when="29 Sep", area="Launglon", line=346, kind="access", site="tha-byar",
         approx=True, en="The Tha Byar bridge on the Dawei–Launglon road is found undermined; lorries are sent round "
                         "by Way Di."),
    dict(t="2026-09-29T14:00", when="29 Sep, afternoon", area="District", line=383, kind="toll",
         en="Dawei Watch confirms about 30 dead in three townships, 21 of them in Launglon; a Dawei national "
            "organisation's list has 32."),
    dict(t="2026-09-29T16:00", when="29 Sep", area="Thayetchaung", line=257, kind="toll", site="kyauk-aing",
         approx=True, en="The father and son swept away at Kyauk Aing are found dead; Thayetchaung's toll reaches "
                         "eight."),
    dict(t="2026-09-29T18:00", when="29 Sep, evening", area="Launglon", line=369, kind="rescue",
         site="launglon-town", en="Mon and Kayin rescue teams, 29 people with two rescue vehicles, camp at Launglon's "
                                  "San Kin monastery."),
    dict(t="2026-09-29T19:00", when="29 Sep, evening", area="Dawei", line=355, kind="recede", site="dawei-town",
         en="The water has largely gone from Dawei; power returns to some wards."),
    dict(t="2026-09-29T20:00", when="29 Sep, night", area="Launglon", line=372, kind="rescue", site="taw-kye",
         en="The blocked road south opens as far as Taw Kye."),
    dict(t="2026-09-29T21:00", when="29 Sep, night", area="Tanintharyi", line=335, kind="flood", site="ban-pyayt",
         en="The water is still rising at Ban Pyae, where the whole village is under."),
    dict(t="2026-09-30T08:00", when="30 Sep, morning", area="Launglon", line=303, kind="access", site="tha-byar-bridge",
         en="The Tha Byar bridge collapses; no vehicle can cross."),
    dict(t="2026-09-30T08:30", when="30 Sep, morning", area="Dawei", line=341, kind="recede", site="pauk-taing-road",
         en="With the water down, the road beside the Pauk Taing bridge is seen eaten away."),
    dict(t="2026-09-30T10:00", when="30 Sep", area="Launglon", line=317, kind="rescue", site="tha-byar", approx=True,
         en="The Tanintharyi Region emergency team sets out with seven vehicles and medical teams for Tha Byar, Kayin "
            "Gyi and Kan Pa Ni."),
    dict(t="2026-09-30T11:00", when="30 Sep", area="Launglon", line=234, kind="access", site="kayin-gyi", approx=True,
         en="Relief teams patch the road at the Kayin Gyi bridge with a backhoe and dump trucks."),
    dict(t="2026-09-30T12:00", when="30 Sep", area="Launglon", line=275, kind="rescue", site="taw-kye", approx=True,
         en="Rescue teams reach Taw Kye; Kyauk Ni Maw, where about 200 people drink rainwater, is perhaps four days "
            "away."),
    dict(t="2026-09-30T13:00", when="30 Sep", area="Tanintharyi", line=284, kind="flood", site="ta-ku", approx=True,
         en="With no rain, the river keeps rising in Ta Ku tract; some houses are under to the roof."),
    dict(t="2026-09-30T14:00", when="30 Sep", area="Launglon", line=224, kind="rescue", site="za-lut-pyin-gyi",
         approx=True, en="The man dug out at Za Lut Pyin Gyi on 26 Sep is handed to rescuers and taken to Dawei "
                         "hospital."),
    dict(t="2026-09-30T15:00", when="30 Sep, 3 pm", area="Tanintharyi", line=246, kind="recede", site="chaung-la-mu",
         en="The water falls about 6 in in Chaung La Mu tract; lorries cross, but about 60 passenger vehicles stay "
            "stuck."),
]

QUOTES = [
    dict(site="kyauk-ni-maw", line=1178, by="Kyauk Ni Maw resident, a man, 26 Sep",
         mm="အိမ်တွေ လမ်းတွေ မြေဖုံးကုန်ပြီ။ အသက်ကြီး တစ်ယောက်ကိုလည်း ကျွန်တော်တို့ သွားခေါ်ထုတ်ထားတယ်။ မြေဖုံးနေတဲ့ ကလေး နှစ်ယောက်ကိုလည်း လောလောဆယ် ကယ်ထုတ်ထားတယ်။ မြေကအခုအထိ ဆက်ပြိုနေတုန်း အရေးပေါ်အကူအညီတွေ လိုနေတယ်",
         en="Houses and roads are buried. We went and brought out an old person, and we've pulled out two "
            "children who were buried. The ground is still collapsing. We need emergency help."),
    dict(site="sit-pyay", line=1161, by="Sit Pyay resident, 26 Sep",
         mm="တစ်ရွာလုံးလည်း ပင်လယ်ပြင်ကြီးလိုဖြစ်သွားပြီ။ လူတွေလည်း ညမအိပ်ရဲကြဘူး။ တောင်ပြိုမှာကြောက်နေကြတယ်",
         en="The whole village has turned into an open sea. People don't dare sleep at night. They're afraid "
            "of landslides."),
    dict(site="ka-det-nge-htein", line=1087, by="Kadet Nge [Htein] resident, 27 Sep",
         mm="သေတဲ့သူတွေ မနည်းဘူး။ နှစ်လောင်းပဲ ထုတ်လို့ရသေးတယ်",
         en="So many are dead. We've only been able to bring out two bodies."),
    dict(site="poe-zar-pin", line=964, by="Zambu Thiri rescue team member, 27 Sep",
         mm="ဒါကြောင့် ပိတ်မိနေတဲ့ မြေကြီးကိုပဲတူးပြီး ကျွန်တော်တို့ ဆက်သွားဖို့ စီစဉ်နေတယ်။ ဘက်ဟိုးတွေလည်း အကူအညီတောင်းထားတယ်",
         en="So we're planning to dig through the earth that's blocking us and carry on. We've asked for "
            "backhoes too."),
    dict(site="kin-shey", line=1068, by="Kin Shey resident, a woman, 27 Sep",
         mm="တစ်သက်နဲ့တစ်ကိုယ် တစ်ခါမှ မမြင်ဖူးဘူး။ ကျွန်မတို့ရွာမှာ ရေတက်လာလည်း ဒူးဆစ်လောက်ပဲ တက်ဖူးတယ်။ အခုက လူတစ်ရပ်လောက်အထိ မြုပ်တယ်။",
         en="I've never seen anything like it in my life. When water rose in our village it only ever came "
            "up to the knee. Now it's over a person's height."),
    dict(site="thin-kyun", line=1029, by="Thin Kyun resident, a man, 3:30 pm 27 Sep",
         mm="ကားကြီးတွေတော့ သွားလို့ရပေမဲ့ ကားငယ်တွေနဲ့ ဆိုင်ကယ်တွေတော့ ဖြတ်ဖို့မလွယ်ဘူး။ အခု (ညနေ ၃ နာရီခွဲ) တော့ ရေ ၂ ပေလောက် ပြန်ကျသွားပြီ",
         en="Big vehicles can get through, but it's hard for small cars and motorbikes. Now (3:30 pm) the "
            "water has dropped about two feet."),
    dict(site="taung-pyauk", line=953, by="Taung Pyauk area resident, 27 Sep",
         mm="လူတွေတော့ အန္တရာယ် မရှိဘူးဗျ။ ကျွဲနွားတော့ ဆုံးရှုံးတယ်ဗျ",
         en="The people are safe. But we've lost buffalo and cattle."),
    dict(site="kyauk-maw-ward", line=934, by="Kyauk Maw ward resident, Dawei, 27 Sep",
         mm="ရေမဝင်တဲ့နေရာ မရှိတော့ဘူး။ ရေဝင်နည်းတာနဲ့ ရေဝင်များတာပဲကွာတယ်။ အရင်က ရေမဝင်ဖူးတဲ့နေရာတွေတောင် ခြေမျက်စိနားလောက် ရေရောက်နေတယ်",
         en="There's nowhere the water hasn't got in. The only difference is how much. Even places that never "
            "flooded have water up to the ankle."),
    dict(site="dawei-town", line=926, by="Dawei resident, morning of 28 Sep",
         mm="လျှပ်စစ်မီးလည်း မလာသေးဘူး ။ မိုးလည်းရွာနေသေးတယ် ။ ညကထက်စာရင်တော့ မိုးရွာ နည်းနည်းလျော့တယ် ။ ညက တစ်ညလုံးစိမ်ပြီး ရွာလိုက်တာ ရေအတိုးမြန်လို့ မအိပ်ဘဲစောင့်ကြည့်ခဲ့ရတယ်",
         en="Still no electricity, and it's still raining, a little less than last night. It poured all night "
            "and the water rose so fast we stayed up watching it."),
    dict(site="pa-kar-ri", line=863, by="Pa Kar Ri resident, night of 27 Sep",
         mm="မြေနိမ့်ပိုင်းတွေ လူအရပ် မမီတော့ဘူး",
         en="In the low-lying parts the water is over a person's head."),
    dict(site="kayin-gyi", line=849, by="Kayin Gyi resident, a man, 28 Sep",
         mm="အရှေ့ပိုင်းတစ်ခြမ်းစာ မြေဖုံးသွားပြီး တံတားနားက လမ်းပိုင်းလည်း ပြတ်သွားတယ်",
         en="The whole eastern half is buried under earth, and the road by the bridge is cut."),
    dict(site="tha-kyet", line=840, by="Tha Kyet resident, Tanintharyi, 28 Sep",
         mm="ညကတည်းက ချောင်း‌‌ရေလျှံတယ်။ စမြုပ်နေပြီ နည်းနည်းမြင့်တဲ့ အိမ်တွေလောက်ကျန်ပြီ",
         en="The stream has been overflowing since last night. It's going under; only the slightly higher "
            "houses are left."),
    dict(site="ka-det-nge-htein", line=829, by="Search-and-rescue official, 28 Sep",
         mm="ရှာဖွေ ကယ်ဆယ်ရေးတွေ စလုပ်နေပြီပေါ့နော်။ အခုအထိတော့ ပိတ်မိနေသူတွေကို ရှာဖွေတာတွေ လုပ်ဆောင်နေပါတယ်။ အသေးစိတ် စာရင်းအတိအကျတော့ တက်မလာ သေးဘူး",
         en="Search and rescue has started. We're still looking for the people who are trapped. We don't have "
            "an exact list yet."),
    dict(site="nyaw-pyin", line=820, by="DDMSC information officer, 28 Sep",
         mm="အကူအညီက လုံးဝမရသေးဘူး။ ထားဝယ်က ဆင်းလာကူညီတဲ့အဖွဲ့ကလည်း အောက်ရေဖြူအထိပဲ ရောက်သေးတယ်။ အောက်ဘက်ရွာတွေအထိ ရောက်အောင် အတော်ဆင်းရဦးမယ်။",
         en="There's been no help at all. The team that came down from Dawei has only got as far as Auk Yay "
            "Phyu. It'll take a lot to reach the villages further south."),
    # ---- 29 Sep update
    dict(site="way-di", line=808, by="Way Di resident, a man, 28 Sep",
         mm="လမ်းမမှာ ရေက နည်းနည်းပဲကျန်ပြီ။ လယ်ထဲတော့ ရှိသေးတယ်။ ဝါးတင်တဲ့ ထော်လာဂျီတွေ သွားနေကြပြီ",
         en="There's only a little water left on the road. The fields are still flooded. The tractors carrying "
            "bamboo are moving again."),
    dict(site="thayetchaung-town", line=780, by="Myat Parami charity member, Thayetchaung, 28 Sep",
         mm="ကိုယ့်မြို့ထဲမှာ ဖြစ်နေတာကို ကိုယ်မကယ်နိုင်ဘဲ ဖြစ်နေတယ်။ အဓိကတော့ လှေမရှိတဲ့ဒဏ်ပေါ့။",
         en="It's happening in our own town and we can't rescue people. Above all, we have no boats."),
    dict(site="kyar-inn", line=761, by="Kyar Inn resident, a woman, 28 Sep",
         mm="တစ်ရွာလုံးက အထဲမှာ ပိတ်မိနေကြတာပါရှင်။ တစ်ယောက်မှ ထွက်မရဘူး",
         en="The whole village is trapped inside. Not one person can get out."),
    dict(site="ka-det-gyi", line=720, by="Villager who dug out the bodies, Kadet Gyi, 28 Sep",
         mm="ဒီနေ့မှ သူတို့ခြံထဲ ဝင်ရှာကြတာ ခြံတစ်ခြံလုံးက တောင်ပြိုမြေတွေနဲ့ ပြည့်နေပြီ အလောင်းကို မနည်းဖော်ထုတ်လာရတယ်",
         en="Only today could we go into their orchard to look. The whole orchard was full of slide earth; it took "
            "a lot to dig the bodies out."),
    dict(site="dawei-town", line=709, by="U Naing Myo Thwin, Tanintharyi Region emergency rescue team, 28 Sep",
         mm="စပြီး ကယ်ထုတ်လာကတည်းက တချို့က အဝတ်အထည်တွေ ယူချိန်မရတဲ့သူတွေ ရှိတယ်။",
         en="Since we started bringing people out, some of them had no time to take any clothes."),
    dict(site="ka-det-nge-htein", line=701, by="Kadet Nge Htein resident, 28 Sep",
         mm="လုံးဝပျက်စီးတာ ၃၁ ဆောင်။ မြေဝင်ဖုံးနေတာက အားလုံး ဘောလုံးကွင်း ငါးကွင်းစာလောက်ရှိတယ်။",
         en="Thirty-one houses completely destroyed. The earth covers about five football pitches in all."),
    dict(site="lay-hnya", line=614, by="Lay Hnya resident, a man, 28 Sep",
         mm="မိုးကအခုခဏပြတ်နေပေမဲ့ ဆက်ရွာရင် ရေဆက်လက်တက်လာနိုင်လို့ မြစ်ချောင်းနံဘေးနေထိုင်သူတွေအားလုံး ကြိုတင်ပြင်ပြီး သတိထားဖို့လိုလိမ့်မယ်",
         en="The rain has stopped for now, but if it starts again the water could keep rising, so everyone living "
            "by the rivers and streams needs to get ready and stay alert."),
    dict(site="nyaw-pyin", line=530, by="Nyaw Pyin resident, interviewed on the night of 28 Sep",
         mm="တောင်မပြိုခင်မှာ တောင်အော်တယ်လို့ သူကပြောပြတယ်။ လေယာဥ်ပျံအသံလိုမျိုး အသံကြမ်းတယ်ပေါ့။ တစ်ရွာလုံးဟိန်းသွားတယ်တဲ့။",
         en="He said the hill roared before it fell. A harsh sound, like an aeroplane. The whole village rang "
            "with it."),
    dict(site="tha-byar", line=551, by="Neighbour of the missing mother and son, a woman, 29 Sep",
         mm="သူ့ဘဝလည်း သနားစရာ။ ထောင်ကနေ လွတ်လာတာ သုံးနှစ်တောင် မပြည့်သေးဘူး။ မိသားစုနဲ့ ပြန်ဆုံရတာ ခဏလေးပဲ ရှိသေးတယ်",
         en="His life is so sad. He's been out of prison less than three years; he'd only just got back to his "
            "family."),
    dict(site="ta-ku", line=507, by="Tanintharyi Township resident, 29 Sep",
         mm="ရေက တက်လာတာ သုံးရက်အတွင်း တော်တော်မြန်တယ်။ ထားဝယ်ဘက်က ရေတွေ ဆင်းလာလို့လည်း ပါမယ်ထင်တယ်။",
         en="The water has come up very fast in three days. I think it's partly the water coming down from "
            "Dawei."),
    dict(site="tanintharyi-town", line=482, by="Tanintharyi town resident, 29 Sep",
         mm="ဒီမှာ မနေ့ကတည်းက မိုးတိတ်နေပေမဲ့ ထားဝယ်ဘက်က ရေဆင်းလာတော့ မြစ်ရေတိုးလာတာ",
         en="The rain stopped here yesterday, but the water coming down from the Dawei side is raising the "
            "river."),
    dict(site="kyauk-ni-maw", line=457, by="Kyauk Ni Maw villager coordinating aid from outside, 29 Sep",
         mm="ရွာထဲ ကျန်နေတဲ့လူတွေချည်းပဲ လက်နဲ့ ရှင်းလင်းရှာဖွေနေရတာပေါ့။ ဘက်ဟိုးလည်း မရှိ၊ ဘာယန္တရားမှလည်း မရှိ",
         en="It's only the people left in the village clearing and searching, by hand. No backhoe, no machinery "
            "at all."),
    dict(site="ti-zit", line=445, by="Ti Zit resident, 29 Sep",
         mm="အခု တာဝါတိုင်မှာရှိနေတဲ့ ဆီကုန်ရင် ဆက်သွယ်ရေးလည်း ရတော့မှာ မဟုတ်ဘူး။ လောလောဆယ်တော့ ရွာက ဈေးဆိုင်တွေမှာ ရှိတဲ့ ရိက္ခာတွေနဲ့ပဲ စားနေသောက်နေကြရပါတယ်။ ဒါကုန်ရင် မရှိတော့ဘူး",
         en="When the fuel at the phone tower runs out, we'll lose contact too. For now we're living on what the "
            "village shops had. When that's gone, there's nothing."),
    # ---- 30 Sep update
    dict(site="za-lut-pyin-gyi", line=227, by="Za Lut Pyin Gyi resident, a man, 30 Sep",
         mm="ကား၊ ဆိုင်ကယ် သွားလို့မရဘူး။ ခက်ခက်ခဲခဲနဲ့ ခြေကျင်သွားနေရတယ်။ လောလောဆယ် လိုတာက စားစရာနဲ့ အဝတ်အထည်တွေပဲ လိုတယ်",
         en="Cars and motorbikes can't get through. We're going on foot, and it's hard. What we need right now is food "
            "and clothes."),
    dict(site="chaung-la-mu", line=246, by="Chaung La Mu tract resident, 3 pm 30 Sep",
         mm="ကုန်ကားတွေက အခု (ညနေ ၃နာရီ) ဖြတ်နေကြပြီ။ ဖြတ်ရတဲ့နေရာတွေတော့ စဖြတ်နေပြီ။ ဖြတ်မရတဲ့နေရာတွေလည်း ရှိနေသေးတယ်။ ခရီးသည်ကားတွေကတော့ လုံးဝဖြတ်လို့မရသေးဘူး",
         en="The lorries are crossing now (3 pm). Where it can be crossed, they've started; there are still places "
            "that can't. Passenger vehicles can't get through at all yet."),
    dict(site="ka-nyin-chaung", line=265, by="Myat Parami charity official, 29 Sep",
         mm="အခုက ကျွန်တော်တို့ ကညင်ချောင်းတံတားဘက်ကို ရောက်နေတယ်။ အဲဒီမှာ ကညင်ချောင်းတံတား ပြိုကျပျက်စီးသွားလို့ အဲဒါကို ပြင်ဖို့လုပ်နေကြတယ်။ ဒီတံတားကို ပြင်ပြီးမှ လူရော၊ ကားတွေရော သွားလာလို့ရမှာ",
         en="We're at the Ka Nyin Chaung bridge now. It has collapsed, and we're working to fix it. Only once it's "
            "repaired can people and vehicles get across."),
    dict(site="kyet-sar-pyin", line=267, by="Woman of Kyet Sar Pyin, Thayetchaung, 29 Sep",
         mm="ကျွန်မတို့ရွာတွေဘက်ကိုလည်း နည်းနည်းလောက် ကူညီပေးပါ။ ကျွန်မတို့ရွာတွေမှာ ကူညီပေးတဲ့အဖွဲ့တွေ ရောက်မလာဘူး။ ကိုယ့်မှာရှိတာလေးနဲ့ ဝေမျှစားသောက်နေကြရတယ်။ ရေတွင်းတွေ ရေကြီးနစ်မြုပ်ကုန်တာဖြစ်လို့ သောက်သုံးရေကလည်း အဓိက လိုအပ်နေတယ်",
         en="Please help our villages a little too. No aid groups come here. We share out the little we have. The "
            "wells are flooded, so drinking water is what we need most."),
    dict(site="kyauk-aing", line=258, by="Rescue volunteer in the Taung Pyauk area, 29 Sep",
         mm="လတ်တလောအခြေအနေကတော့ အိမ်တွေမှာ ရွှံ့ဗွက်တွေ တအားတင်နေတယ်။ အဲဒါတွေကို ကိုယ်ထူကိုယ်ထပဲ ဆေးကြောနေရတယ်။ လူသေတာက ကျောက်အိုင်မှာ သားအဖနှစ်ဦးက အလောင်းပြန်ရပြီဆိုကြားတယ်",
         en="Right now the houses are deep in mud, and people are washing it out themselves. As for the dead, I hear "
            "the bodies of the father and son at Kyauk Aing have been found."),
    dict(site="kyauk-ni-maw", line=274, by="Aid coordinator relaying Kyauk Ni Maw residents, 30 Sep",
         mm="ရွာမှာ ပိတ်မိနေတာ လူနှစ်ရာလောက်က သောက်သုံးရေအတွက် အဓိကအခက်အခဲ ဖြစ်နေတယ်။ ခိုလှုံနေတဲ့ ဘုန်းကြီးကျောင်းမှာ သိုလှောင်ထားတဲ့ ရေကလည်း နည်းလာနေတယ်။ အခု မိုးရေခံသောက်နေကြရတယ်",
         en="For the 200 or so people trapped in the village, drinking water is the main problem. The water stored at "
            "the monastery where they're sheltering is running low. Now they're catching rain to drink."),
    dict(site="za-lut", line=277, by="Kyauk Ni Maw villager, 30 Sep",
         mm="ဇလွတ်မှာ မြေပြိုထားတဲ့နေရာကလည်း လောင်းလုံးဆိုင်းဘုတ်အနားမှာ မြေပြိုထားတာကို ရှင်းသလို ရှင်းရဖို့ရှိနေတယ်။ နောက်အချိန် လေးရက်လောက်နေမှ ကျောက်နီမော်ကို ရောက်နိုင်မယ်",
         en="The slide at Za Lut will have to be cleared the way they cleared the one by the Launglon signboard. It'll "
            "be about four more days before they can reach Kyauk Ni Maw."),
    dict(site="ta-ku", line=285, by="Ta Ku resident, 30 Sep",
         mm="ရေက မြစ်ရေရော၊ အင်းရေရော အစုံတက်၊ အကုန်တက်နေတယ်။ အချို့အိမ်တွေဆို အိမ်ခေါင်မိုး မမြင်ရတော့ဘူး။ နေပူနေလည်း ရေက ဆက်တိုးနေတယ်",
         en="The river and the lakes are rising together, everything's rising. Some houses, you can't see the roofs "
            "any more. The sun is out and the water still keeps rising."),
    dict(site="tha-kyet-taw", line=296, by="Tha Kyet Taw resident, a woman, 29 Sep",
         mm="အိမ်တော်တော်များများပဲ စားစရာလိုအပ်တယ်ရှင့်။ လွယ်လွယ်ချက်စားလို့ရတဲ့ဟာမှန်သမျှ အကုန်ပြတ်သွားပြီ",
         en="Most households need food. Anything that's quick to cook has run out."),
    dict(site="tha-byar", line=347, by="Tha Byar resident, a man, 29 Sep",
         mm="မြေပြိုမှု မဖြစ်ခင်ကတည်းက သဲတွေ စုတ်ထားတာလည်းရှိတော့ ဖောင်ဒေးရှင်း နိမ့်ကျနေတာလည်းရှိတယ်။ အခုမြေပြိုပြီး ရေတိုက်စားတဲ့အခါကျတော့ အောက်က မျောတုံးတစ်တုံးပြတ်ဖို့အခြေအနေဖြစ်နေတယ်",
         en="Even before the slide, sand had been pumped out, so the foundations had sunk. Now, with the slide and the "
            "water scouring it, one of the piers underneath is about to break off."),
    dict(site="tha-byar", line=324, by="Tha Byar resident, a man, 30 Sep",
         mm="ဒီလောက် အပျက်အစီးများတာ။ တစ်ဦးတစ်ယောက် အင်အားနဲ့ မလုံလောက်ဘူး။ ဝိုင်းကူမှပဲ ဆင်ပြေနိုင်မယ်",
         en="There's so much damage. One person's strength isn't enough. Only if everyone pitches in will we manage."),
    dict(site="kayin-gyi", line=361, by="Kayin Gyi resident, a woman, 29 Sep",
         mm="ရွာအထက်ပိုင်းအိမ်တွေ ရိက္ခာသယ်လို့မရသလို မျှော်ရစ်ဘက်နဲ့ ကမ်းပနီရွာကိုလည်း ထွက်လို့မရတော့ဘူး",
         en="The houses in the upper village can't bring food in, and there's no way out towards Myaw Yit or to Kan "
            "Pa Ni any more."),
    dict(site="ban-pyayt", line=334, by="Ban Pyae resident, 29 Sep",
         mm="စားရေးသောက်ရေးကတော့ ခက်ခဲပါတယ်။ အဲဒီလိုပဲဖြစ်သလို စားနေရတယ်။ ဒီနှစ်အတွင်း ရေကြီးတာ သုံးကြိမ်မှာ ဒီတစ်ကြိမ် ရေအများဆုံးပဲ။ တစ်ရွာလုံးကို စုံးစုံးမြုပ်နေပြီ",
         en="Food and water are hard. We eat whatever we can get. Of the three floods this year, this is the highest. "
            "The whole village is completely under."),
    dict(site="taw-kye", line=372, by="Shwe Yaung Nay Thit charity official, Myeik, 29 Sep",
         mm="နယ်မြေအခြေအနေအရ အခုရောက်ရှိလာတဲ့အဖွဲ့တွေအားလုံး ဇမ္ဗူသီရိနဲ့ ပူးပေါင်းဆောင်ရွက်နေပါတယ်။ မနက်ဖြန် သရက်ချောင်းမှာ ကျွန်တော်တို့ စဆင်းပြီး ဆောင်ရွက်မယ်။ မွန်၊ ကရင် အဖွဲ့တွေက မနက်ဖြန် လောင်းလုံးမှာ စမယ်။ ပိတ်နေတဲ့လမ်းကတော့ အခုည တောကျဲရွာအထိ ပွင့်သွားပြီ",
         en="Given the situation on the ground, every team that has arrived is working with Zambu Thiri. Tomorrow we "
            "start in Thayetchaung; the Mon and Kayin teams start in Launglon. The blocked road is open as far as Taw "
            "Kye tonight."),
]

# Township-level figures and the storm. `line` = source line.
FACTS = dict(
    record_in=11.02, record_mm=280, prev_record_in=9.68, prev_record_year=1998, record_line=1037,
    sept_mean_mm=707, sept_mean_by="WMO climate normal quoted in the explainer", sept_mean_line=894,
    national_daily_mean_mm=30, national_line=1036,
    forecast_3day_mm=[360, 470], forecast_by="U Win Naing, weather analyst", forecast_line=1020,
    thayetchaung_official=dict(wards=5, depth_ft=[6, 8], affected=18000, line=955,
                               by="military government figures"),
    launglon_villages="20+", launglon_line=852,
    bodies=[  # the Launglon township count as it was reported
        dict(t="2026-09-26T18:00", n=0, line=1179, label="26 Sep: people missing, none recovered"),
        dict(t="2026-09-27T12:00", n=3, line=1061, label="27 Sep noon: 3 bodies"),
        dict(t="2026-09-28T10:00", n=5, line=853, plus=True, label="28 Sep morning: at least 5 bodies"),
        dict(t="2026-09-28T16:00", n=9, line=814, label="28 Sep: 9 dead"),
        dict(t="2026-09-28T19:30", n=12, line=702, label="28 Sep evening: 12 dead"),
        dict(t="2026-09-29T12:00", n=15, line=492, label="29 Sep midday: 15 bodies recovered"),
    ],
    district_dead=[  # Dawei Watch's count for the whole disaster area
        dict(t="2026-09-28T15:00", n=15, line=624, plus=True, label="28 Sep explainer: at least 15 dead"),
        dict(t="2026-09-29T12:00", n=23, line=490, label="29 Sep midday: 23 dead in three townships"),
    ],
    # the 29 Sep midday round-up, place by place (lines 492-501)
    toll_29=dict(dead=23, missing_text="dozens", line=490, places=[
        dict(site="ka-det-nge-htein", dead=10, missing=3, line=493),
        dict(site="ka-det-gyi", dead=2, line=494),
        dict(site="nyaw-pyin", dead=2, line=495),
        dict(site="min-yat", dead=1, line=495),
        dict(site="tha-byar", missing=2, line=495),
        dict(site="kyauk-ni-maw", missing=8, line=495),
        dict(site="saw-hpyar", dead=2, line=498),
        dict(site="ka-nyin-chaung", dead=2, line=498),
        dict(site="thayetchaung-town", dead=2, line=498),
        dict(site="kyauk-aing", missing=2, line=499),
        dict(site="pyar-thar-chaung", dead=2, line=501),
    ]),
    record2_in=13.62, record2_mm=346, record2_line=783,
    villages_hit="40+", villages_hit_line=624,
    thayetchaung_villages="20+", thayetchaung_line=497,
    # 17 ft is the alert (စိုးရိမ်) mark and 24 ft the danger (အန္တရာယ်) mark (line 481)
    tanintharyi_river=dict(alert_ft=17, danger_ft=24, line=481, history_line=487, readings=[
        dict(t="2026-09-27T12:00", ft=15, approx=True, line=1136, label="27 Sep: about 2 ft below the alert mark"),
        dict(t="2026-09-29T15:00", ft=26, plus=True, line=480, label="29 Sep, ~3 pm: over 26 ft"),
    ], history="In 2026 the river passed its alert mark in July, August and September, and its danger mark in "
               "August and again now."),
    history=[dict(year=1994, line=1168, text="Heavy rain brought hills down in Launglon, killing people and "
                                            "destroying hundreds of acres of orchards."),
             dict(year=1997, line=1041, text="Launglon residents recall large landslides like these."),
             dict(year=1997, line=799, text="At Pa Nyit a slide buried about 100 houses and 61 people died in the "
                                            "mud, villagers say.")],
    storm=[
        dict(line=873, en="21 Sep: Thailand's meteorological department warns of heavy to very heavy rain, "
                         "flash floods and landslides for 23–27 Sep as a low moves in from central Vietnam."),
        dict(line=882, en="26 Sep: the low, crossing Cambodia and Thailand, meets a strong south-west monsoon "
                         "over the Andaman Sea. Record rain floods Bangkok; heavy rain at Dawei."),
        dict(line=890, en="The Tanintharyi range lifts the moist monsoon air and wrings the rain out on its "
                         "Andaman-facing side (orographic lift)."),
        dict(line=892, en="Hillsides already soaked by the monsoon take in more water than they can hold; pore "
                         "pressure rises and slopes fail."),
        dict(line=928, en="28 Sep: DMH expects the low to strengthen into a depression and move north and "
                          "north-west, across the Gulf of Mottama towards the Ayeyarwady delta."),

        dict(line=783, en="28 Sep: DMH records 13.62 in (346 mm) at Dawei, a second record in two days. Rain "
                          "stops over most of the area from midday."),
        dict(line=792, en="DMH has warned that a strong El Niño set in this September, bringing erratic rain, "
                          "heat, storms and drought."),
    ],
)


# 30 Sep update
FACTS["bodies"].append(dict(t="2026-09-29T15:00", n=21, line=386, label="29 Sep afternoon: 21 bodies recovered"))
FACTS["district_dead"].append(dict(t="2026-09-29T15:00", n=30, approx=True, line=383,
                                   label="29 Sep afternoon: about 30 dead in three townships"))
FACTS["district_dead_other"] = dict(n=32, line=383, by="a Dawei national organisation (ထားဝယ်အမျိုးသားအဖွဲ့ချုပ်)")
FACTS["villages_hit_29"] = dict(total="90+", line=382, launglon=37, launglon_line=386, thayetchaung="30+",
                                thayetchaung_line=409, dawei="24+", dawei_line=416)
FACTS["tanintharyi_river"]["still_rising"] = dict(day=30, line=284, text="Still rising at Ta Ku on 30 Sep, with no "
                                                                         "rain; no gauge figure given.")
# The latest figure for each place: the 29 Sep afternoon round-up (lines 386-416), with Thayetchaung
# from the later 29 Sep post (lines 252-257), whose total of 8 includes the Kyauk Aing father and son.
FACTS["toll"] = dict(dead=31, missing_text="tens", as_of="29 Sep, evening", dw_total=30, dw_line=383, places=[
    dict(site="ka-det-nge-htein", dead=10, missing=5, line=387),
    dict(site="taw-kye", dead=5, line=397),
    dict(site="ka-det-gyi", dead=2, line=389),
    dict(site="nyaw-pyin", dead=2, line=390),
    dict(site="min-yat", dead=1, line=392),
    dict(site="za-lut", dead=1, line=397),
    dict(site="tha-byar", missing=2, line=393),
    dict(site="kyauk-ni-maw", missing=8, line=395),
    dict(site="saw-hpyar", dead=2, line=256),
    dict(site="ka-nyin-chaung", dead=2, line=256),
    dict(site="thayetchaung-town", dead=2, line=256),
    dict(site="kyauk-aing", dead=2, line=257),
    dict(site="pyar-thar-chaung", dead=2, line=416),
], by_ts=dict(Launglon=dict(dead=21, line=386), Thayetchaung=dict(dead=8, line=252), Dawei=dict(dead=2, line=416)))

# Lifelines: the state of roads, bridges, power, phones, rescue and food supply by
# area, as of the latest post that mentions it. status: cut | disrupted | working |
# needed. `line` is the file line (1-based), like everywhere else in this file.
LIFELINE_COLS = [("road", "Roads"), ("bridge", "Bridges"), ("power", "Power"), ("comms", "Phone and internet"),
                 ("rescue", "Rescue teams"), ("supplies", "Food and water")]
LIFELINES = [
    dict(area="Launglon south", sub="Beyond Nyin Maw", cells=dict(
        road=dict(s="cut", day=29, line=461, t="Backhoes have cleared the road only as far as Nyin Maw. Slides still "
                                              "block the hill road to Ti Zit and nearly every village further "
                                              "south."),
        bridge=dict(s="cut", day=29, line=465, t="Many bridges destroyed on the road from Kyauk Ni Maw down to "
                                                "Shin Maw."),
        comms=dict(s="cut", day=29, line=454, t="Kyauk Ni Maw reachable only through villagers who find a signal; "
                                               "Ti Zit's phone tower is running out of fuel."),
        rescue=dict(s="disrupted", day=29, line=493, t="A dozen-strong advance team at Kadet Nge Htein since 28 Sep; "
                                                      "no team has reached Kyauk Ni Maw, Ti Zit, Za Lut or Nyaw "
                                                      "Pyin."),
        supplies=dict(s="needed", day=29, line=447, t="Ti Zit's 1,000-plus people live on shop stocks; 200-plus at "
                                                     "Kyauk Ni Maw's monastery need food and medicine."))),
    dict(area="Launglon north and town", sub="Ka Myaw Gyi to Nyin Maw", cells=dict(
        road=dict(s="working", day=28, line=803, t="Water fell on the evening of 28 Sep at Ka Myaw Gyi, Way Di, Min "
                                                   "Yat, Tha Byar and in Launglon town."),
        rescue=dict(s="working", day=28, line=590, t="Teams based at Nyin Maw, where relief supplies are collected "
                                                     "and handed out."),
        supplies=dict(s="needed", day=28, line=596, t="Food, clothes and above all drinking water: the slides "
                                                      "wrecked the village wells."))),
    dict(area="Launglon west coast", sub="Maungmagan, Kayin Gyi, Pa Nyit", cells=dict(
        road=dict(s="cut", day=28, line=797, t="Slides on the road either side of Pa Nyit."),
        bridge=dict(s="cut", day=28, line=848, t="Kayin Gyi's bridge and village roads destroyed."),
        comms=dict(s="cut", day=28, line=798, t="Shan Maw, Pein Ne Chaung and Kyone Ga Nan, beyond Pa Nyit, cut "
                                                "off and out of contact."),
        rescue=dict(s="working", day=28, line=588, t="Teams from Maungmagan working the Kayin Gyi and Kan Pa Ni "
                                                     "side."),
        supplies=dict(s="needed", day=28, line=641, t="Kayin Gyi's residents in the monastery, short of food."))),
    dict(area="Dawei town", sub="15 MIMU wards", cells=dict(
        road=dict(s="working", day=29, line=541, t="Water falling in the wards on the morning of 29 Sep; people "
                                                   "back home cleaning up."),
        power=dict(s="cut", day=29, line=545, t="Off since 27 Sep; still off at midday on 29 Sep."),
        comms=dict(s="disrupted", day=28, line=713, t="Some phone lines down until at least the evening of 28 Sep."),
        rescue=dict(s="working", day=28, line=707, t="Residents of seven wards moved out overnight on 27 Sep; the "
                                                     "Red Cross giving health care."),
        supplies=dict(s="needed", day=28, line=705, t="600-plus people in five monasteries need food, clothes and "
                                                      "medicine."))),
    dict(area="East of Dawei", sub="Dawei–Htee Khee road", cells=dict(
        road=dict(s="cut", day=28, line=714, t="Impassable between Byaw Taw Wa and Za Lun on 28 Sep; Pa Kar Ri "
                                               "under water; one lane past a slide at Tha Yet Ngoke."),
        bridge=dict(s="cut", day=28, line=864, t="San Chi bridge under water."),
        supplies=dict(s="needed", day=28, line=658, t="Pa Kar Ri tract villagers in monasteries need food."))),
    dict(area="Thayetchaung", sub="And the Dawei–Myeik road", cells=dict(
        road=dict(s="cut", day=28, line=756, t="Ka Nyin Chaung bridge on Union Road No. 8 destroyed; the "
                                               "Dawei–Myeik road is cut."),
        bridge=dict(s="cut", day=28, line=572, t="Ka Nyin Chaung bridge; two rope bridges at Mei Ke; rope bridges "
                                                 "in the Taung Pyauk area."),
        power=dict(s="cut", day=29, line=468, t="Still off on 29 Sep, after the water fell."),
        comms=dict(s="cut", day=29, line=468, t="Phone lines down because the power is off."),
        rescue=dict(s="cut", day=28, line=779, t="Only a local charity, with no boats; the district's teams are "
                                                 "all in Launglon."),
        supplies=dict(s="needed", day=29, line=474, t="Drinking water, food and clothes, and help clearing silt. "
                                                     "Wells flooded; the town market's food lost."))),
    dict(area="Palaw", sub="Myeik District, south on the highway", cells=dict(
        road=dict(s="disrupted", day=27, line=1031, t="Flooded stretches between Palaw, Palauk and Pala; "
                                                     "vehicles stranded."))),
    dict(area="Tanintharyi", sub="Myeik District, on the river", cells=dict(
        road=dict(s="cut", day=29, line=486, t="5 ft of water on the Tanintharyi–Kawthoung road at Lel Taung Yar; "
                                              "the Myeik road under water at Aw Gyi."),
        bridge=dict(s="cut", day=29, line=506, t="Low roads and bridges under water in Ta Ku, Thar Ra Bwin and Thein "
                                                "Daw; people use boats and rafts."),
        comms=dict(s="disrupted", day=29, line=510, t="Phone lines cut, on and off."))),
]


# 30 Sep update: cells replaced by what the later posts say
LIFELINES_30 = {
    "Launglon south": dict(
        road=dict(s="cut", day=30, line=275, t="Open to Taw Kye from the night of 29 Sep; on 30 Sep teams were digging "
                                              "towards Tha Win. The big slide at Za Lut still stands between them and "
                                              "Kyauk Ni Maw, perhaps four days' work."),
        rescue=dict(s="disrupted", day=30, line=275, t="Teams reached Taw Kye on 30 Sep. None has reached Kyauk Ni Maw, "
                                                      "Za Lut, Tha Kyet Taw or the Kyauk Twin tract."),
        supplies=dict(s="needed", day=30, line=274, t="About 200 at Kyauk Ni Maw drink rainwater; Tha Kyet Taw and the "
                                                     "villages beyond it out of food since 27 Sep; Kyauk Twin's 350 "
                                                     "households short of food.")),
    "Launglon north and town": dict(
        road=dict(s="disrupted", day=30, line=305, t="With the Tha Byar bridge down, all traffic goes round by the Inn "
                                                    "Zauk junction, Way Di and Pyin Htein."),
        bridge=dict(s="cut", day=30, line=303, t="The Tha Byar bridge on the Dawei–Launglon road collapsed on the "
                                                "morning of 30 Sep."),
        rescue=dict(s="working", day=30, line=318, t="The Region emergency team at Tha Byar with seven vehicles and "
                                                     "medical teams; Mon and Kayin teams based at Launglon's San Kin "
                                                     "monastery since 29 Sep."),
        supplies=dict(s="needed", day=30, line=326, t="Drinking water, clothes and food; Tha Byar's slide earth must be "
                                                      "cleared before people can go home.")),
    "Launglon west coast": dict(
        road=dict(s="disrupted", day=30, line=235, t="The road at the Kayin Gyi bridge was patched on 30 Sep, so relief "
                                                    "can reach Kayin Gyi, Kan Pa Ni and Pa Nyit; the Kan Pa Ni–Pa Nyit "
                                                    "road is still buried in two places."),
        bridge=dict(s="disrupted", day=30, line=234, t="The cut approach to the Kayin Gyi bridge temporarily repaired "
                                                      "with a backhoe and dump trucks."),
        rescue=dict(s="working", day=30, line=239, t="The Region emergency team and partners giving relief and medical "
                                                    "care at Kayin Gyi."),
        supplies=dict(s="needed", day=30, line=237, t="Nearly 100 houses destroyed at Kayin Gyi and Kan Pa Ni; "
                                                     "hundreds living in monasteries.")),
    "Dawei town": dict(
        road=dict(s="working", day=29, line=352, t="The water had largely gone by the evening of 29 Sep; some fallen "
                                                   "trees still to clear."),
        power=dict(s="disrupted", day=29, line=355, t="Back in some wards on the evening of 29 Sep; still off in "
                                                      "others.")),
    "Thayetchaung": dict(
        road=dict(s="cut", day=30, line=342, t="Bok Taung's slide still blocks the Myeik–Dawei road on 30 Sep; the "
                                               "road by the Pauk Taing bridge, leaving Dawei, is eaten away."),
        bridge=dict(s="cut", day=29, line=264, t="The Ka Nyin Chaung bridge is down, and relief cannot get past it to "
                                                "Pe Det; two rope bridges at Mei Ke gone."),
        rescue=dict(s="disrupted", day=29, line=371, t="The Myeik group Shwe Yaung Nay Thit brings machinery to clear "
                                                       "the road with Zambu Thiri from 30 Sep."),
        supplies=dict(s="needed", day=29, line=266, t="Drinking water, food, clothes, blankets and mosquito nets; wells "
                                                     "flooded.")),
    "Tanintharyi": dict(
        road=dict(s="disrupted", day=30, line=242, t="Water down about 6 in at Chaung La Mu on 30 Sep: lorries pass, "
                                                    "about 60 passenger vehicles stranded, nine stretches to Yay Phyu "
                                                    "still under water."),
        bridge=dict(s="cut", day=30, line=287, t="Roads and bridges under water in Ta Ku tract; boats and rafts only."),
        supplies=dict(s="needed", day=29, line=332, t="Ban Pyae's families on a hill drink rainwater with no food "
                                                      "supply; 300-plus households moved to high ground in Chaung La Mu "
                                                      "tract.")),
}
for _row in LIFELINES:
    _row["cells"].update(LIFELINES_30.pop(_row["area"], {}))
if LIFELINES_30:
    raise SystemExit(f"LIFELINES_30: unknown areas {list(LIFELINES_30)}")


# ---------------------------------------------------------------------------
# 1 Oct update: the later 30 Sep posts and the 1 Oct posts (lines 68-217). 1 Oct is day 31.
# ---------------------------------------------------------------------------
TIP_FOOD = ("Named among the villages at the tip of the Launglon peninsula whose food has run out and that urgently "
            "need help (1 Oct).")
MSM_ROAD = ("Villagers were clearing the road slides themselves on 30 Sep; the village lies on the road to the Myat "
            "Shin Maw pagoda, one of the nine Shins. Drinking water and food are needed.")
TNI_EXPL = ("Among more than 50 villages in ten tracts along the Tanintharyi River under water, with tens of thousands "
            "moving out (1 Oct explainer).")
TNI_WHOLE = "Among the riverside villages entirely under water since 29 Sep (1 Oct explainer)."
TKU_THIRDS = "Two-thirds of the village under water (1 Oct)."
TNI_ROAD = ("The Tanintharyi–Bokpyin road is under at least 4 ft of water here, a traveller says; many vehicles are "
            "stranded.")

MORE01 = {
    # ---------------------------------------------- Launglon
    "launglon-town": [
        R(77, "affected", "More than 20 villages in the township hit since the heavy rain began on 25 Sep."),
        R(103, "affected", "Launglon's toll from the floods and slides reaches 26 by 1 Oct (Kadet Nge Htein post)."),
        R(76, "affected", "A later 1 Oct post, on Taw Kye, puts the township's toll at 31."),
    ],
    "ka-det-nge-htein": [
        R(100, "fatal", "Six days after the slide, on 1 Oct, the body of another woman was dug out: Ma Tin Tin Phyu, 27, "
                       "of the village."),
        R(102, "fatal", "Twelve bodies recovered; three people still missing.", dead=12, missing=3),
    ],
    "taw-kye": [
        R(70, "fatal", "Slides since the night of 26 Sep destroyed 42 houses and killed five: two men, a Buddhist nun and "
                      "two women.", dead=5, houses=42),
        R(74, "fatal", "Three bodies, Daw Mi Thein (Mae Au Gut), U La Gyit and Ko Min Min, are still under the earth; "
                      "the nun Mi Shin (Ma Auk) and Ma Zar were recovered and buried."),
        R(78, "fatal", "The machinery teams clearing the slide-blocked roads were near Taw Kye on 1 Oct.",
          roles=["access"]),
        R(213, "fatal", "By 30 Sep the rescue teams clearing the road had got only this far, about 4 miles from Launglon "
                        "town."),
    ],
    "kyauk-ni-maw": [
        R(134, "fatal", "97 houses destroyed by slides, and a small boy and a man killed. The post gives no missing "
                       "figure; earlier posts said five to eight were missing, and these two may be among them.",
          dead=2, houses=97),
        R(136, "fatal", "Houses lost: 24 at Ann Ni Twin, 34 in the upper new quarter, 28 in the lower new quarter and 11 "
                       "in the middle of the village."),
        R(137, "fatal", "The dead, from one house, are an uncle and nephew: a boy of 1 year 3 months and Maung Aung Naing "
                       "Myo, 29. The child's body has not been found."),
        R(140, "fatal", "Nearly 200 people whose houses fell live in the monastery and the houses left standing, and "
                       "urgently need clothes, food and drinking water.", sheltering=200, roles=["relief", "needs"]),
        R(141, "fatal", "Those with money cross by boat to buy food on the far shore; the rest feed their children snails "
                       "and nipa fruit."),
        R(143, "fatal", "The Tanintharyi Region emergency team and partners were to go in by sea on 1 Oct.",
          roles=["relief"]),
        R(83, "fatal", "Video: those who can afford it buy food across the water by boat; the rest eat snails and nipa "
                       "fruit."),
    ],
    "nyaw-pyin": [
        R(210, "fatal", "Two women dead and five people hurt, three of whom need specialist treatment. A family of five "
                        "was buried; a young daughter broke her arm and an older one is injured all over.", dead=2,
          roles=["needs"]),
        R(213, "fatal", "More than 40 miles from Launglon town; rescuers clearing the road had reached only Taw Kye by "
                        "30 Sep.", rescue="not-reached", roles=["access"]),
        R(79, "fatal", TIP_FOOD, roles=["needs"]),
    ],
    "ti-zit": [
        R(214, "fatal", "A woman in her 50s died on the night of 28 Sep after a heart attack: with the roads closed she "
                        "was carried to hospital partly overland and partly by water, and arrived too late.", dead=1),
        R(216, "fatal", "Still cut off; residents' photos show clearing begun on the Yin Boke–Ti Zit road on 30 Sep.",
          roles=["access"]),
    ],
    "tha-kyet-taw": [
        R(79, "affected", TIP_FOOD, roles=["needs"]),
        R(195, "affected", "Video: food that is quick to cook has run out, and nearly every household needs it.",
          roles=["needs"]),
    ],
    **{k: [R(79, "affected" if k not in ("za-lut-pyin-gyi",) else "fatal", TIP_FOOD, roles=["needs"])]
       for k in ("kyauk-pon", "ra-be", "za-lut-pyin-gyi", "kyauk-twin", "sun-gyi", "chaung-hpyar-gyi", "wea-ma-kaik",
                 "kyauk-wut-pyin")},
    "auk-kyauk-wut": [R(79, "affected", TIP_FOOD, roles=["needs"]), R(147, "affected", MSM_ROAD, roles=["access", "needs"])],
    "kyet-hlut": [R(79, "affected", TIP_FOOD, roles=["needs"]), R(147, "affected", MSM_ROAD, roles=["access", "needs"])],
    # ---------------------------------------------- Tanintharyi
    "tanintharyi-town": [
        R(198, "affected", "29 ft 2 in on the evening of 30 Sep, more than 5 ft over the danger mark; most townspeople "
                           "living by the river have moved out.", river_ft=29.17, roles=["relief"]),
        R(203, "affected", "Rising since 28 Sep: the town, riverside villages and stretches of the "
                           "Myeik–Tanintharyi–Kawthoung road are under water."),
        R(192, "affected", "A little over a foot short of the 2024 flood's 31 ft (the 1994 record is 36 ft 4 in)."),
        R(182, "affected", "Tens of thousands have fled the water in the township, but only the town is getting aid; "
                           "the villages get none.", roles=["relief"]),
        R(95, "affected", "More than 100 villages in over 20 tracts under water and tens of thousands moving out "
                          "(1 Oct)."),
    ],
    "ban-pyayt": [
        R(167, "severe", TNI_EXPL), R(170, "severe", TNI_WHOLE),
        R(186, "severe", "Work is scarce in the rains, and the flood has made feeding families harder still.",
          roles=["needs"]),
        R(89, "severe", "Under water for days; drinking water is now the problem.", roles=["needs"]),
        R(93, "severe", "The river fell about 1 ft by noon on 1 Oct, but the whole village is still under. Residents "
                        "fetch water from the head of the lake.", roles=["needs", "receding"]),
    ],
    "ta-ku": [
        R(167, "severe", TNI_EXPL),
        R(174, "severe", "On 30 Sep, with no rain, residents moved again as the river rose fast: knee-deep inside houses "
                         "within hours."),
        R(106, "severe", "Three days without rain, the river still rising on 1 Oct; more residents moving out.",
          roles=["relief"]),
        R(109, "severe", "Low-lying houses under to the roofs; the lake water and the river have met."),
        R(110, "severe", "Many of the displaced are day labourers and rubber tappers; food is needed.", roles=["needs"]),
        R(113, "severe", "About 3,000 households in the tract; hundreds have fled the water."),
    ],
    "kyauk-sa-yit": [
        R(170, "severe", TNI_WHOLE),
        R(172, "severe", "Roads and houses under water, boats the only transport; residents have moved to higher ground.",
          roles=["access", "relief"]),
        R(111, "severe", "The whole village under water (1 Oct)."),
    ],
    "ywar-ma": [R(111, "severe", "The whole village under water (1 Oct).")],
    "ta-ku-nge": [R(111, "severe", TKU_THIRDS)],
    "wan-nar": [R(170, "severe", TNI_WHOLE), R(111, "severe", TKU_THIRDS)],
    "taik-kan": [R(170, "severe", TNI_WHOLE), R(111, "severe", TKU_THIRDS)],
    "mya-yar-chaung": [R(170, "severe", TNI_WHOLE)],
    "koe-inn": [R(170, "severe", TNI_WHOLE)],
    "maw-tone": [R(167, "severe", TNI_EXPL), R(170, "severe", TNI_WHOLE)],
    "pa-wa": [R(167, "severe", TNI_EXPL), R(170, "severe", TNI_WHOLE)],
    **{k: [R(167, "affected", TNI_EXPL)] for k in ("thein-daw", "thar-ra-bwin", "ban-law")},
    "chaung-la-mu": [
        R(167, "severe", TNI_EXPL),
        R(188, "severe", "War-displaced people from other villages, renting houses here, have had to move again.",
          roles=["relief", "needs"]),
    ],
    "aw-gyi": [R(180, "affected", TNI_ROAD, depth_ft=4, roles=["access"])],
}
_BY = {s["id"]: s for s in SITES}  # rebuilt: SITES grew after the last index
for _k, _rs in MORE01.items():
    _BY[_k]["reports"].extend(_rs)

SITES += [
    # ================================================== Launglon, the peninsula's tip
    dict(id="kyauk-mat-tat", mm="ကျောက်မတ္တပ်", en="Kyauk Mat Tat", ts="Launglon", area="Launglon south",
         hazard="landslide", mimu_mm="ကျောက်မတ်တတ်", match="variant",
         match_note="MIMU spells it ကျောက်မတ်တတ် (Kyauk Mat Tat), the village tract's main village.",
         reports=[R(79, "affected", TIP_FOOD, roles=["needs"]), R(147, "affected", MSM_ROAD, roles=["access", "needs"])]),

    # ================================================== Tanintharyi, along the river
    dict(id="myay-ma-ohn", mm="မြေမအုံ", en="Myay Ma Ohn", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[
             R(89, "severe", "The whole village under water for days; drinking water is now short.", roles=["needs"]),
             R(90, "severe", "Near Tanintharyi town. Houses under water since 26 Sep; with nowhere to move to, residents "
                             "are living on rafts.", roles=["relief"]),
             R(91, "severe", "Flat land with no high ground and nowhere to draw water: drinking water urgently needed.",
               roles=["needs"]),
         ]),
    dict(id="yae-paw", mm="ရေပေါ်", en="Yay Paw", ts="Tanintharyi", area="Tanintharyi", hazard="flood", reports=[
        R(86, "severe", "Video: some families crowd into two-storey houses still above water; others live on platforms "
                        "built in their upper floors.", roles=["relief"]),
        R(116, "severe", "The whole village under water; residents trapped, unable to move out."),
        R(117, "severe", "Went under on 30 Sep as the river kept rising. People crowd into the upper floors of two-storey "
                        "houses the water has not reached; others have built platforms in the dry part of their upper "
                        "floors.", roles=["relief"]),
        R(120, "severe", "Still rising on 1 Oct, so more people are moving; with no rain, drinking water is short.",
          roles=["needs"]),
        R(123, "severe", "More than 200 households."),
    ]),
    dict(id="tha-mee-hla", mm="သမီးလှ", en="Tha Mee Hla", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[
             R(86, "severe", "Video: named with Yay Paw as under water, with residents trapped."),
             R(116, "severe", "Named with Yay Paw as entirely under water, residents trapped."),
             R(121, "severe", "A third of the village under water, the post's text says; moving out is hard, with no high "
                             "ground and the hills far off."),
             R(123, "severe", "More than 300 households."),
         ]),
    dict(id="ah-lel-paing", mm="အလယ်ပိုင်း", en="Ah Lel Paing", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         vt_hint="Ta Ku", reports=[R(111, "severe", TKU_THIRDS)]),
    dict(id="chauk-ein-su", mm="ခြောက်အိမ်စု", en="Chauk Ein Su", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="unlocated", match_note="Named as a Ta Ku tract village; not in MIMU village points.",
         reports=[R(111, "severe", TKU_THIRDS)]),
    dict(id="sin-chay-hpone", mm="ဆင်ခြေဖုံး", en="Sin Chay Hpone tract", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt="Tanintharyi Sin Chay Hpone",
         match_note="A village tract (MIMU: တနင်္သာရီဆင်ခြေဖုံး, Tanintharyi Sin Chay Hpone); shown at the tract's centre.",
         reports=[R(167, "affected", TNI_EXPL)]),
    dict(id="ban-la-mut", mm="ဘန်းလမွတ်", en="Ban La Mut tract", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", match="approx", approx_vt="Ban La Mut",
         match_note="A village tract; shown at the tract's centre.", reports=[R(167, "affected", TNI_EXPL)]),
    # the Tanintharyi–Bokpyin road
    *[dict(id=i, mm=mm, en=en, ts="Tanintharyi", area="Tanintharyi", hazard="flood", **kw,
           reports=[R(180, "affected", TNI_ROAD, depth_ft=4, roles=["access"])])
      for i, mm, en, kw in [
          ("yan-hpo", "ရမ်းဖို", "Yan Hpo", {}),
          ("sin-din", "ဆင်ဒင်", "Sin Din", {}),
          ("pyin-wun", "ပြင်ဝန်း", "Pyin Wun", {}),
          ("ka-de-leik", "ကဒဲလိပ်", "Ka De Leik", dict(
              mimu_mm="ကတဲလိပ်", match="probable",
              match_note="Taken as MIMU's Ka De Leik (ကတဲလိပ်), Maw Tone (East) tract; the post spells it ကဒဲလိပ်.")),
          ("auk-kin-east", "အောက်ကင်းအရှေ့", "Auk Kin (East)", dict(
              mimu_mm="အောက်ကင်း (အရှေ့)", match="variant",
              match_note="MIMU writes it အောက်ကင်း (အရှေ့), Auk Kin (East), in Tanintharyi Sin Chay Hpone tract.")),
      ]],
]

INCIDENTS += [
    dict(id="tni-bokpyin-road", kind="flooded-road", en="Highway 4 ft+ under water west of Tanintharyi",
         mm="တနင်္သာရီ-ဘုတ်ပြင်း ကားလမ်း", between=["sin-din", "aw-gyi"], line=180, day=31,
         text="At least 4 ft of water over the Tanintharyi–Bokpyin road, as the post calls it, at Yan Hpo, Sin Din, "
              "Pyin Wun, Ka De Leik, Aw Gyi and Auk Kin (East), a traveller says; many vehicles are stranded. On MIMU's "
              "map the six villages lie along the highway north-west of Tanintharyi town, towards Myeik.",
         match_note="Placed midway between Sin Din and Aw Gyi, the ends of the flooded stretch, then moved onto the "
                    "nearest MIMU road."),
    dict(id="myat-shin-maw-road", kind="road-block", en="Slides on the Myat Shin Maw road", mm="မြတ်ရှင်မော်လမ်း",
         between=["auk-kyauk-wut", "kyauk-mat-tat"], line=147, day=31,
         text="Slides block the road to the Myat Shin Maw pagoda at Kyet Hlut, Auk Kyauk Wut and Kyauk Mat Tat; "
              "villagers were clearing them themselves on 30 Sep.",
         match_note="Placed midway between Auk Kyauk Wut and Kyauk Mat Tat, then moved onto the nearest MIMU road."),
]
for _i in INCIDENTS:
    if _i["id"] == "ti-zit-road":
        _i["text"] += " Clearing began on the Yin Boke–Ti Zit stretch on 30 Sep, residents' photos show (line 216)."

TIMELINE += [
    dict(t="2026-09-26T21:30", when="26 Sep, night", area="Launglon", line=71, kind="landslide", site="taw-kye",
         en="Slides begin at Taw Kye; they will destroy 42 houses and kill five."),
    dict(t="2026-09-28T22:00", when="28 Sep, night", area="Launglon", line=214, kind="toll", site="ti-zit",
         en="A Ti Zit woman in her 50s dies of a heart attack after a slow journey to hospital by land and water."),
    dict(t="2026-09-30T09:30", when="30 Sep", area="Launglon", line=147, kind="access", site="myat-shin-maw-road",
         approx=True, en="Villagers at Kyet Hlut, Auk Kyauk Wut and Kyauk Mat Tat clear slides from their own road."),
    dict(t="2026-09-30T10:30", when="30 Sep", area="Launglon", line=216, kind="access", site="ti-zit", approx=True,
         en="Clearing starts on the Yin Boke–Ti Zit road."),
    dict(t="2026-09-30T12:30", when="30 Sep", area="Tanintharyi", line=117, kind="flood", site="yae-paw", approx=True,
         en="Yay Paw goes entirely under as the river keeps rising."),
    dict(t="2026-09-30T18:00", when="30 Sep, evening", area="Tanintharyi", line=198, kind="flood",
         site="tanintharyi-town", en="The Tanintharyi River reaches 29 ft 2 in, more than 5 ft over its danger mark; "
                                    "most riverside townspeople have moved out."),
    dict(t="2026-10-01T08:00", when="1 Oct", area="Launglon", line=143, kind="rescue", site="kyauk-ni-maw", approx=True,
         en="The Region emergency team and partners set out by sea for Kyauk Ni Maw, still cut off by road."),
    dict(t="2026-10-01T09:00", when="1 Oct", area="Launglon", line=78, kind="rescue", site="taw-kye", approx=True,
         en="Road-clearing machinery is near Taw Kye."),
    dict(t="2026-10-01T10:00", when="1 Oct", area="Launglon", line=100, kind="toll", site="ka-det-nge-htein",
         approx=True, en="Another woman's body is dug out at Kadet Nge Htein: 12 dead there, three still missing."),
    dict(t="2026-10-01T12:00", when="1 Oct, noon", area="Tanintharyi", line=93, kind="recede", site="ban-pyayt",
         en="The river falls about 1 ft at Ban Pyae, but the whole village is still under."),
    dict(t="2026-10-01T13:00", when="1 Oct", area="Tanintharyi", line=106, kind="flood", site="ta-ku", approx=True,
         en="Three days without rain, the river is still rising in Ta Ku tract and at Yay Paw; more people move out."),
    dict(t="2026-10-01T14:00", when="1 Oct", area="Launglon", line=103, kind="toll", site="launglon-town", approx=True,
         en="Launglon's toll reaches 26; a later post the same day says 31."),
    dict(t="2026-10-01T15:00", when="1 Oct", area="Launglon", line=134, kind="toll", site="kyauk-ni-maw", approx=True,
         en="Kyauk Ni Maw counts 97 houses destroyed and two dead, a man and a small boy."),
    dict(t="2026-10-01T16:00", when="1 Oct", area="Launglon", line=70, kind="toll", site="taw-kye", approx=True,
         en="Taw Kye counts five dead, three of them still under the earth, and 42 houses destroyed."),
]

# mm=None: the Myanmar words are taken from the source line itself (see main)
QUOTES += [
    dict(site="taw-kye", line=73, by="Woman of Taw Kye, 1 Oct", mm=None,
         en="My brother was caught in the slide at Taw Kye. We still haven't dug out his body. There are three bodies "
            "not yet recovered."),
    dict(site="kyauk-ni-maw", line=138, by="Kyauk Ni Maw resident, a man, 1 Oct", mm=None,
         en="They were from the same house, uncle and nephew. We still haven't found where the child's body is. The "
            "adult's body already smells."),
    dict(site="kyauk-ni-maw", line=141, by="Kyauk Ni Maw resident, a man, 1 Oct", mm=None,
         en="People who have money can go by boat and buy things on the other shore. Those who don't pick up snails "
            "and gather nipa fruit to feed their children. That's how they're getting by."),
    dict(site="nyaw-pyin", line=212, by="Volunteer helping Nyaw Pyin, 30 Sep", mm=None,
         en="For now the village treats them as best it can. Five in one family were buried. The little daughter broke "
            "her arm, and an older one has wounds all over her body. As soon as the road opens, getting them treated "
            "has to come first."),
    dict(site="ti-zit", line=215, by="Launglon resident who knew of the death, 30 Sep", mm=None,
         en="The village health worker treated her heart attack as best they could. With the roads closed we had no "
            "choice but to take her partly by land and partly by water. She reached the hospital, but too late, and "
            "died."),
    dict(site="myay-ma-ohn", line=92, by="Woman of Myay Ma Ohn, 1 Oct", mm=None,
         en="It's low ground, so when the river rises even a little we go under. The flood has gone on so many days "
            "there's no drinking water left."),
    dict(site="yae-paw", line=119, by="Yay Paw resident, 1 Oct", mm=None,
         en="The houses where we're crowded together are packed, with people and with belongings. Those with nowhere "
            "to go have built platforms in their own flooded upper floors and live there."),
    dict(site="tha-mee-hla", line=122, by="Tha Mee Hla resident, 1 Oct", mm=None,
         en="Yay Paw and Tha Mee Hla have no high ground, and the hills are far away. It's hard to move. The sun is "
            "out and the water keeps rising. I've never known that before; it used to fall when the sun came out."),
    dict(site="ta-ku", line=112, by="Ta Ku resident, 1 Oct", mm=None,
         en="Clumps of bamboo keep floating down the river. People are moving to houses on higher ground. Usually at "
            "this time of year the water rises fast and falls fast. This time it just keeps rising."),
    dict(site="ta-ku", line=175, by="Ta Ku tract resident, 30 Sep", mm=None,
         en="In the early morning the water was by the house; by midday it was in the house, knee-deep. It came that "
            "fast."),
    dict(site="tanintharyi-town", line=178, by="Farmer on the Tanintharyi River, 30 Sep", mm=None,
         en="This is the third flood this year. This time the losses could be bigger. Bamboo and trees are floating "
            "down the river. When the water falls there could be landslides."),
    dict(site="chaung-la-mu", line=189, by="Volunteer helping war-displaced families, Chaung La Mu, 30 Sep", mm=None,
         en="They're borrowing to eat. It's harder for them than for the villagers."),
]

FACTS["bodies"].append(dict(t="2026-10-01T14:00", n=26, line=103, label="1 Oct: 26 dead in Launglon (Kadet Nge Htein "
                                                                       "post)"))
FACTS["bodies_alt"] = dict(t="2026-10-01T18:00", n=31, line=76, label="1 Oct, later: 31 dead in Launglon (Taw Kye post)")
FACTS["district_dead"].append(dict(t="2026-10-01T12:00", n=30, plus=True, line=130,
                                   label="1 Oct: more than 30 dead in Launglon, Thayetchaung and Dawei"))
FACTS["tanintharyi_river"]["readings"].append(dict(t="2026-09-30T18:00", ft=29.17, line=198,
                                                   label="30 Sep, evening: 29 ft 2 in"))
FACTS["tanintharyi_river"]["records"] = [dict(year=1994, ft=36.33, label="36 ft 4 in", line=200),
                                         dict(year=2024, ft=31, label="31 ft", line=200)]
FACTS["tanintharyi_river"]["still_rising"] = dict(
    day=31, line=106, t="2026-10-01T12:00",
    text="1 Oct, three days without rain: still rising at Ta Ku and Yay Paw; down about 1 ft at Ban Pyae by noon. No "
         "new gauge height.")
FACTS["tni_flooded"] = [
    dict(day=29, villages="20-odd", tracts="9", line=505, label="29 Sep"),
    dict(day=31, villages="50+", tracts="20+", line=166, label="30 Sep explainer"),
    dict(day=31, villages="100+", tracts="20+", displaced="tens of thousands", line=95, label="1 Oct"),
]
# Aid from outside the region that the posts report. 1 lakh = 100,000 kyats.
FACTS["aid"] = [
    dict(by="Dawei Sangha Union, Yangon", mm="ရန်ကုန်ရောက် ထားဝယ်သံဃသမဂ္ဂ", lakh=363, line=128, day=31,
         to="Launglon and Thayetchaung",
         note="Monks of 44 Yangon monasteries from Dawei District; decided on 30 Sep, four abbots to take it in person."),
    dict(by="DYOK Dawei Association, Korea", mm="DYOK ထားဝယ်အသင်း (ကိုရီးယား)", lakh=123, line=154, day=30,
         to="Launglon", note="Given on 28 Sep through Launglon relief groups; a fundraising futsal match in Gimpo on "
                             "4 Oct is for the other townships."),
]
# Latest figure for each place as of 1 Oct. Launglon adds up to the 26 of the Kadet Nge Htein post (line 103),
# counting the Ti Zit woman who could not reach hospital. The Taw Kye post's 31 (line 76) is that 26 plus Taw Kye's
# five, which the 29 Sep round-up had already counted; the page shows it but does not use it.
FACTS["toll_30"] = FACTS["toll"]
FACTS["toll"] = dict(dead=36, as_of="1 Oct", dw_total=30, dw_plus=True, dw_line=130, places=[
    dict(site="ka-det-nge-htein", dead=12, missing=3, line=102),
    dict(site="taw-kye", dead=5, line=70),
    dict(site="ka-det-gyi", dead=2, line=389),
    dict(site="nyaw-pyin", dead=2, line=210),
    dict(site="kyauk-ni-maw", dead=2, line=134),
    dict(site="min-yat", dead=1, line=392),
    dict(site="za-lut", dead=1, line=397),
    dict(site="ti-zit", dead=1, line=214, indirect=True),
    dict(site="tha-byar", missing=2, line=306),
    dict(site="saw-hpyar", dead=2, line=256),
    dict(site="ka-nyin-chaung", dead=2, line=256),
    dict(site="thayetchaung-town", dead=2, line=256),
    dict(site="kyauk-aing", dead=2, line=257),
    dict(site="pyar-thar-chaung", dead=2, line=416),
], by_ts=dict(Launglon=dict(dead=26, line=103), Thayetchaung=dict(dead=8, line=252), Dawei=dict(dead=2, line=416)))

LIFELINE_COLS.insert(5, ("health", "Medical care"))
LIFELINES_01 = {
    "Launglon south": dict(
        road=dict(s="cut", day=31, line=78, t="Machinery clearing the slides was near Taw Kye on 1 Oct, about 4 miles "
                                              "from town. At the tip, Kyet Hlut, Auk Kyauk Wut and Kyauk Mat Tat clear "
                                              "their own road."),
        rescue=dict(s="disrupted", day=31, line=143, t="By road, teams had got no further than Taw Kye by 30 Sep. The "
                                                      "Region emergency team and partners set out by sea for Kyauk Ni "
                                                      "Maw on 1 Oct."),
        health=dict(s="cut", day=30, line=210, t="Five hurt at Nyaw Pyin, three needing specialist care, wait for the "
                                                 "road to open; a Ti Zit woman died after reaching hospital too late. "
                                                 "Health workers are needed."),
        supplies=dict(s="needed", day=31, line=79, t="Food has run out from Tha Kyet Taw to Kyet Hlut and in the Kyauk "
                                                     "Twin tract; at Kyauk Ni Maw, those with no money eat snails and "
                                                     "nipa fruit.")),
    "Tanintharyi": dict(
        road=dict(s="cut", day=31, line=180, t="At least 4 ft of water on the Tanintharyi–Bokpyin road at six villages "
                                               "from Yan Hpo to Auk Kin; stretches of the Myeik–Tanintharyi–Kawthoung "
                                               "road under water."),
        bridge=dict(s="cut", day=31, line=169, t="Roads and bridges under water; people get about by boat and raft."),
        rescue=dict(s="cut", day=31, line=182, t="Tens of thousands displaced, but only Tanintharyi town is getting "
                                                 "aid; the villages have none."),
        supplies=dict(s="needed", day=31, line=185, t="Drinking water, with the wells under: Ban Pyae and Myay Ma Ohn "
                                                      "most of all. Food for day labourers, rubber tappers and "
                                                      "war-displaced families.")),
}
for _row in LIFELINES:
    _row["cells"].update(LIFELINES_01.pop(_row["area"], {}))
if LIFELINES_01:
    raise SystemExit(f"LIFELINES_01: unknown areas {list(LIFELINES_01)}")


# ---------------------------------------------------------------------------
# 2 Oct update: the seven 2 Oct posts (lines 1-67; lines 1-2 are separator rules). 2 Oct is day 32.
# The 2 Oct round-up (lines 54-67) gives every death place by place, to 1 Oct.
# ---------------------------------------------------------------------------
KTL = ("The whole Kyauk Ta Lone tract, its four villages included, has been under water for more than a week; "
       "drinking water, medicine and food are urgently needed (2 Oct).")
RU02 = "Named in the 2 Oct round-up, whose figures run to 1 Oct."

MORE02 = {
    # ---------------------------------------------- Launglon
    "launglon-town": [
        R(58, "affected", "At least 45 wards and villages in the township hit; 31 dead from the slides by 1 Oct (2 Oct "
                          "round-up)."),
        R(53, "affected", "Launglon's toll from the slides reaches 31 by 1 Oct (Tha Byar post)."),
        R(20, "affected", "Video: Launglon's toll from the floods and slides reaches 31."),
        R(23, "affected", "No plan yet to restore power to the township's cut-off villages, the junta's deputy electricity "
                          "minister told its parliament on 1 Oct.", roles=["comms"]),
        R(29, "affected", "The town's 33/11 kV substation lost its main transformer to heavy weapons in fighting on 30 Sep "
                          "2025; more than 40 villages north and south of the town have had no power for over a year.",
          roles=["comms"]),
        R(31, "affected", "Rubber, bakery, cold-store and local factories run on generators and solar at a loss; some have "
                          "closed."),
    ],
    "ka-det-nge-htein": [
        R(59, "fatal", "15 dead, the most of any village. On 1 Oct the count was 12 dead and three missing; the round-up "
                       "names no one missing, so the page takes the three as among the 15.", dead=15, missing=0),
    ],
    "taw-kye": [R(59, "fatal", "Five dead, a Buddhist nun among them: the second-highest toll.", dead=5)],
    "tha-byar": [
        R(49, "fatal", "The bodies of all three members of a local family buried by the slide have been recovered, the "
                       "Region's emergency rescue and ambulance association says.", dead=3, missing=0),
        R(50, "fatal", "Searching the slide earth west of the main road, rescuers found Daw Aye Win, about 50, and her "
                       "granddaughter Ma Pyone Ei Soe, 6, on 30 Sep."),
        R(51, "fatal", "On 1 Oct they found the girl's mother, Ma Thin Pa Pa Soe."),
        R(52, "fatal", "The three died in the floods and slides on the night of 26 Sep; nearly 40 houses were buried or "
                       "damaged."),
        R(18, "fatal", "Video: the bodies of the three family members recovered."),
        R(60, "fatal", "Three of one family dead (2 Oct round-up).", dead=3),
    ],
    "ka-det-gyi": [R(60, "fatal", "Two dead (2 Oct round-up).", dead=2)],
    "nyaw-pyin": [R(60, "fatal", "Two dead (2 Oct round-up).", dead=2)],
    "kyauk-ni-maw": [R(60, "fatal", "Two dead (2 Oct round-up); no missing figure given.", dead=2)],
    "min-yat": [R(60, "fatal", "One dead (2 Oct round-up).", dead=1)],
    "za-lut-pyin-gyi": [R(60, "fatal", "One dead (2 Oct round-up): the death the 29 Sep round-up placed at Za Lut, "
                                       "probably U Tun Po.", dead=1)],
    "za-lut": [R(60, "fatal", "The 2 Oct round-up places Za Lut's one death at Za Lut Pyin Gyi, so it is counted there.",
                 dead=0)],
    "ti-zit": [R(61, "fatal", "The round-up adds an elderly man who died when slide-blocked roads kept him from treatment in "
                              "time, outside its 31. The 30 Sep post described a woman in her 50s; the page takes them as "
                              "the same death.")],
    # ---------------------------------------------- Thayetchaung and Dawei
    "thayetchaung-town": [
        R(62, "fatal", "At least 44 wards and villages in the township hit by floods and slides; eight dead by 1 Oct."),
        R(63, "fatal", "Two dead in the town (2 Oct round-up).", dead=2),
    ],
    **{k: [R(63, "fatal", "Two dead (2 Oct round-up).", dead=2)] for k in ("saw-hpyar", "ka-nyin-chaung", "kyauk-aing")},
    "dawei-town": [R(64, "affected", "At least 31 wards and villages in the township flooded: 14 town wards and 17 "
                                     "villages (2 Oct round-up).")],
    "pyar-thar-chaung": [R(65, "fatal", "Two children killed when a tree fell in the fast-flowing floodwater.", dead=2)],
    # ---------------------------------------------- Tanintharyi
    "tanintharyi-town": [
        R(37, "severe", "Nearly the whole town, on the river bank, under water; thousands of townspeople moving to safety.",
          roles=["relief"]),
        R(39, "severe", "Rising since 28 Sep and over the danger mark from 29 Sep; on 2 Oct it rose again and many more "
                        "townspeople moved out."),
        R(41, "severe", "30 ft 2 in on the morning of 2 Oct, more than 6 ft over the 24 ft danger mark.", river_ft=30.17),
        R(42, "severe", "Internet patchy and the power cut.", roles=["comms"]),
        R(43, "severe", "With no power, the township Red Cross's water purifier is idle; it plans to share drinking water "
                        "treated with purification tablets.", roles=["needs"]),
        R(44, "severe", "By 30 Sep the junta's information department listed eight relief camps in the town and more than "
                        "1,000 townspeople moved.", sheltering=1000, roles=["relief"]),
        R(45, "severe", "The Myeik–Tanintharyi–Kawthoung Union road and villages along the river flooded.",
          roles=["access"]),
        R(5, "severe", "Video: internet and power cut; drinking water short.", roles=["needs"]),
        R(17, "severe", "About 140 of the township's 160-plus villages under water (2 Oct)."),
        R(67, "severe", "Floods in more than 50 villages, affecting tens of thousands (2 Oct round-up)."),
    ],
    "myay-ma-ohn": [R(10, "severe", KTL, roles=["needs"])],
}
_BY = {s["id"]: s for s in SITES}  # rebuilt: SITES grew after the last index
for _k, _rs in MORE02.items():
    _BY[_k]["reports"].extend(_rs)

SITES += [
    dict(id="kyauk-ta-lone", mm="ကျောက်တလုံး", en="Kyauk Ta Lone", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         reports=[
             R(8, "severe", "Houses in the tract under water for more than a week; drinking water urgently needed.",
               roles=["needs"]),
             R(9, "severe", "The river has risen since 26 Sep and was still rising on 2 Oct; there is no drinking water "
                            "left."),
             R(10, "severe", "The whole tract under water: Kyauk Ta Lone, Myay Ma Ohn, Kyein Chaung Wa and Kwin Waing."),
             R(12, "severe", "Flat land with no high ground: nowhere to draw drinking water.", roles=["needs"]),
             R(13, "severe", "People falling sick in the heat with too little clean water; medicine needed.",
               roles=["needs"]),
             R(14, "severe", "Households share their rice, which is nearly gone; help is needed.", roles=["needs"]),
             R(15, "severe", "The water rose more slowly on 2 Oct."),
             R(16, "severe", "Some live on rafts, some on platforms in half-submerged houses, some on platforms in the "
                             "monastery.", roles=["relief"]),
         ]),
    dict(id="kyein-chaung-wa", mm="ကြိမ်ချောင်းဝ", en="Kyein Chaung Wa", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", reports=[R(10, "severe", KTL, roles=["needs"])]),
    dict(id="kwin-waing", mm="ကွင်းဝိုင်း", en="Kwin Waing", ts="Tanintharyi", area="Tanintharyi", hazard="flood",
         match="approx", approx_vt="Kyauk Ta Lone",
         match_note="Named as a Kyauk Ta Lone tract village; MIMU's only Kwin Waing in the township, Kwin Waing 5-Maing "
                    "(ကွင်းဝိုင်း ၅-မိုင်), is filed under Ban Law tract about 9 km away. Shown at Kyauk Ta Lone tract's "
                    "centre.",
         reports=[R(10, "severe", KTL, roles=["needs"])]),
    dict(id="chaung-gyi-ward", mm="ချောင်းကြီးရပ်ကွက်", en="Chaung Gyi ward", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", ward_mm="ချောင်းကြီးရပ်ကွက်",
         reports=[R(38, "severe", "Almost the whole ward under water.")]),
    dict(id="chaung-nge-ward", mm="ချောင်းငယ်ရပ်ကွက်", en="Chaung Nge ward", ts="Tanintharyi", area="Tanintharyi",
         hazard="flood", ward_mm="ချောင်းငယ်ရပ်ကွက်",
         reports=[R(38, "severe", "Most of the ward under water.")]),
]

TIMELINE += [
    dict(t="2026-09-30T10:00", when="30 Sep", area="Launglon", line=50, kind="toll", site="tha-byar", approx=True,
         en="Searchers find Daw Aye Win and her granddaughter, 6, under the Tha Byar slide."),
    dict(t="2026-09-30T17:00", when="30 Sep", area="Tanintharyi", line=44, kind="rescue", site="tanintharyi-town",
         approx=True, en="The junta lists eight relief camps in Tanintharyi town, with more than 1,000 townspeople moved."),
    dict(t="2026-10-01T10:30", when="1 Oct", area="Launglon", line=24, kind="comms", site="launglon-town", approx=True,
         en="In the junta's parliament, its deputy electricity minister says there is no plan yet to restore power to "
            "Launglon's villages, dark since Sep 2025."),
    dict(t="2026-10-01T11:00", when="1 Oct", area="Launglon", line=51, kind="toll", site="tha-byar", approx=True,
         en="The girl's mother is found at Tha Byar: all three of the family are recovered."),
    dict(t="2026-10-02T08:00", when="2 Oct, morning", area="Tanintharyi", line=41, kind="flood", site="tanintharyi-town",
         en="The river at Tanintharyi reaches 30 ft 2 in, more than 6 ft over its danger mark; nearly the whole town is "
            "under water and thousands move out."),
    dict(t="2026-10-02T11:00", when="2 Oct", area="Tanintharyi", line=15, kind="flood", site="kyauk-ta-lone",
         approx=True, en="Kyauk Ta Lone tract, under water for over a week, runs out of drinking water; the rise slows."),
    dict(t="2026-10-02T12:00", when="2 Oct", area="Dawei District", line=56, kind="toll", site="launglon-town",
         approx=True, en="Dawei Watch counts at least 41 dead to 1 Oct: 31 in Launglon, 8 in Thayetchaung, 2 in Dawei."),
]

QUOTES += [
    dict(site="kyauk-ta-lone", line=11, by="Kyauk Ta Lone tract resident, 2 Oct", mm=None,
         en="The sun is hot, there's flood below us, and we can't drink our fill of water. Some people don't get water at "
            "all. The water we drew before the wells went under is gone too."),
    dict(site="kyauk-ta-lone", line=15, by="Kyauk Ta Lone tract resident, 2 Oct", mm=None,
         en="Those who have rice are sharing it. More and more people are falling sick. Today the water is rising more "
            "slowly."),
    dict(site="launglon-town", line=25, by="U Aye Kyaw, junta deputy electricity minister, in its parliament, 1 Oct",
         mm=None,
         en="Because of the situation on the ground, the damaged transformer and electrical equipment can't be repaired "
            "yet. We can supply power only after they have been inspected and repaired."),
]

# Launglon's count: the 1 Oct Taw Kye post's 31 (line 76), which this page's 1 Oct edition set aside as counting
# Taw Kye twice, is confirmed place by place by the 2 Oct round-up: it is Kadet Nge Htein's 15 and Tha Byar's 3.
FACTS["bodies"].append(dict(t="2026-10-01T18:00", n=31, line=76, label="1 Oct, later: 31 dead in Launglon (Taw Kye post)"))
FACTS["bodies"].append(dict(t="2026-10-02T12:00", n=31, line=58,
                            label="2 Oct round-up: 31 by 1 Oct, place by place"))
FACTS["bodies_alt"] = None
FACTS["district_dead"].append(dict(t="2026-10-02T12:00", n=41, plus=True, line=56,
                                   label="2 Oct round-up: at least 41 dead in three townships, to 1 Oct"))
FACTS["tanintharyi_river"]["readings"].append(dict(t="2026-10-02T08:00", ft=30.17, line=41,
                                                   label="2 Oct, morning: 30 ft 2 in"))
FACTS["tanintharyi_river"]["slowing"] = dict(day=32, line=15, text="2 Oct: the rise slowed at Kyauk Ta Lone.")
FACTS["tni_flooded"].append(dict(day=32, villages="~140", of="160+", line=17, label="2 Oct",
                                 other=dict(villages="50+", line=67)))
FACTS["launglon_power"] = dict(villages="40+", since="30 Sep 2025", line=30, minister_line=23,
                               plant="20 MW gas-fired plant at Kanbauk", plant_line=33)
# Dawei Watch's own place-by-place count to 1 Oct (2 Oct round-up, lines 56-65). The Ti Zit death, which the
# round-up adds outside its 31, is carried as `indirect` so the places still sum to Dawei Watch's totals.
FACTS["toll_01"] = FACTS["toll"]
FACTS["toll"] = dict(dead=41, as_of="1 Oct", dw_total=41, dw_plus=True, dw_line=56, places=[
    dict(site="ka-det-nge-htein", dead=15, line=59),
    dict(site="taw-kye", dead=5, line=59, unrecovered=3, unrecovered_line=74),
    dict(site="tha-byar", dead=3, line=60),
    dict(site="ka-det-gyi", dead=2, line=60),
    dict(site="nyaw-pyin", dead=2, line=60),
    dict(site="kyauk-ni-maw", dead=2, line=60, unrecovered=1, unrecovered_line=138),
    dict(site="za-lut-pyin-gyi", dead=1, line=60),
    dict(site="min-yat", dead=1, line=60),
    dict(site="ti-zit", indirect=1, line=61),
    dict(site="saw-hpyar", dead=2, line=63),
    dict(site="ka-nyin-chaung", dead=2, line=63),
    dict(site="thayetchaung-town", dead=2, line=63),
    dict(site="kyauk-aing", dead=2, line=63),
    dict(site="pyar-thar-chaung", dead=2, line=65),
], by_ts=dict(Launglon=dict(dead=31, line=58), Thayetchaung=dict(dead=8, line=62), Dawei=dict(dead=2, line=65)))

LIFELINES_02 = {
    "Launglon south": dict(
        power=dict(s="cut", day=32, line=30, t="More than 40 villages north and south of Launglon town have had no power "
                                               "since the town substation was shelled on 30 Sep 2025; on 1 Oct the "
                                               "junta's deputy minister said there is no plan yet to restore it.")),
    "Launglon north and town": dict(
        power=dict(s="cut", day=32, line=23, t="No plan yet to restore power to Launglon's villages, the junta's deputy "
                                               "electricity minister said on 1 Oct; the substation needs repair money "
                                               "from a future budget.")),
    "Tanintharyi": dict(
        road=dict(s="cut", day=32, line=45, t="The Myeik–Tanintharyi–Kawthoung road and riverside villages flooded; on "
                                              "1 Oct at least 4 ft of water over the highway at six villages west of "
                                              "the town."),
        power=dict(s="cut", day=32, line=42, t="Power cut in Tanintharyi town as nearly all of it goes under."),
        comms=dict(s="disrupted", day=32, line=42, t="Internet lines patchy in the town."),
        rescue=dict(s="disrupted", day=32, line=44, t="Eight relief camps in the town by 30 Sep (junta figures); the "
                                                      "villages get no aid."),
        health=dict(s="needed", day=32, line=13, t="People falling sick in Kyauk Ta Lone tract for lack of clean water; "
                                                   "medicine needed."),
        supplies=dict(s="needed", day=32, line=43, t="Drinking water: the Red Cross purifier is idle without power, so it "
                                                     "plans purification tablets. Kyauk Ta Lone tract has no drinking "
                                                     "water and its rice is nearly gone.")),
}
for _row in LIFELINES:
    _row["cells"].update(LIFELINES_02.pop(_row["area"], {}))
if LIFELINES_02:
    raise SystemExit(f"LIFELINES_02: unknown areas {list(LIFELINES_02)}")


def norm(s):
    # dot below (U+1037) and asat (U+103A) are typed in either order; MIMU and the posts differ
    return (s or "").replace("​", "").replace(" ", "").replace("့်", "့်").strip()


def post_index(lines_text):
    """Headline line numbers, ascending, and the post each belongs to."""
    heads = [i for i, t in enumerate(lines_text, 1) if re.match(r"Dawei Watch\s*\|", t)]
    heads = [h - 1 for h in heads]  # the headline is the line before the byline
    return heads


def main():
    text = open(SRC, encoding="utf-8").read().split("\n")
    heads = post_index(text)
    if sorted(p["h"] for p in POSTS) != heads:
        raise SystemExit(f"POSTS headlines {sorted(p['h'] for p in POSTS)} != file {heads}")
    posts = sorted(POSTS, key=lambda p: -p["h"])        # oldest first (bottom of the file)
    for i, p in enumerate(posts, 1):
        p["id"] = f"P{i:02d}"
        p["mm"] = text[p["h"] - 1].strip()
        p["byline"] = text[p["h"]].strip()
        p.setdefault("kind", "News")
    by_head = {p["h"]: p for p in posts}

    def post_of(line):
        k = bisect.bisect_right(heads, line) - 1
        if k < 0:
            raise SystemExit(f"line {line} is before the first post")
        return by_head[heads[k]]

    vp = gpd.read_file(os.path.join(RAW, "village_points_tni.geojson"))
    towns = gpd.read_file(os.path.join(RAW, "town_points.geojson"))
    vt = gpd.read_file(os.path.join(RAW, "adm4_vt_tanintharyi.geojson"))
    wards = gpd.read_file(os.path.join(RAW, "adm5_wards.geojson"))
    bridges = gpd.read_file(os.path.join(RAW, "bridges.geojson"))
    roads = gpd.read_file(os.path.join(RAW, "roads.geojson"))

    # ---------------------------------------------------------------- geocode
    for s in SITES:
        s.setdefault("match", "exact")
        if s["match"] == "unlocated":
            s["lon"] = s["lat"] = None
        elif "town" in s:
            r = towns[towns.Town == s["town"]].iloc[0]
            s.update(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5), pcode=r.Town_Pcode,
                     mimu_name=r.Town + " (town)", mimu_mm=r.Town_MMR4)
        elif "bridge" in s:
            r = bridges[bridges.nmEng == s["bridge"]].iloc[0]
            s.update(lon=round(r.geometry.x, 5), lat=round(r.geometry.y, 5), mimu_name=r.nmEng,
                     mimu_mm=r.nmMya)
        elif "ward" in s or "ward_mm" in s:
            r = (wards[wards.WARD == s["ward"]] if "ward" in s
                 else wards[wards.WARD_MMR.map(norm) == norm(s["ward_mm"])]).iloc[0]
            p = r.geometry.representative_point()
            s.update(lon=round(p.x, 5), lat=round(p.y, 5), pcode=r.WARD_PCODE,
                     mimu_name=r.WARD, mimu_mm=r.WARD_MMR)
        elif "approx_vt" in s:
            names = s["approx_vt"] if isinstance(s["approx_vt"], list) else [s["approx_vt"]]
            rs = vt[vt.VT.isin(names) & (vt.TS == s["ts"])]
            if len(rs) != len(names):
                raise SystemExit(f"{s['id']}: village tracts {names} not all found in {s['ts']}")
            p = rs.geometry.union_all().representative_point()
            s.update(lon=round(p.x, 5), lat=round(p.y, 5), pcode=" ".join(rs.VT_PCODE),
                     mimu_name=" and ".join(rs.VT) + (" (village tracts)" if len(rs) > 1 else " (village tract)"),
                     mimu_mm=" / ".join(rs.VT_MMR))
        else:
            want = norm(s.get("mimu_mm", s["mm"]))
            m = vp[(vp.VLG_MMR.map(norm) == want) & (vp.TS == s["ts"])]
            if "vt_hint" in s:
                m = m[m.VT == s["vt_hint"]]
            if len(m) != 1:
                raise SystemExit(f"{s['id']}: {len(m)} MIMU matches for {want} in {s['ts']}")
            r = m.iloc[0]
            s.update(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5), pcode=str(r.VLG_PCODE),
                     mimu_name=r.VILLAGE, mimu_mm=r.VLG_MMR, vt=r.VT)

    # reference points used by incidents but not themselves reported sites
    extra_pts = {}
    for key, (mm, ts) in {"pyin-htein": ("ပြင်းထိန်", "Launglon"), "kyauk-sin": ("ကျောက်ဆင်", "Launglon"),
                          "ya-laing": ("ရလိုင်", "Yebyu"), "thit-to-htaunt": ("သစ်တိုထောင့်", "Yebyu")}.items():
        r = vp[(vp.VLG_MMR.map(norm) == norm(mm)) & (vp.TS == ts)].iloc[0]
        extra_pts[key] = dict(lon=round(r.Longitude, 5), lat=round(r.Latitude, 5))

    # ---------------------------------------------------------------- reports -> daily state
    SEV = {"affected": 0, "severe": 1, "fatal": 2}
    FIG_KEYS = ["dead", "missing", "missing_text", "rescued", "houses", "houses_text", "sheltering",
                "depth_ft", "affected", "villages", "river_ft"]
    for s in SITES:
        for r in s["reports"]:
            p = post_of(r["line"])
            r["post"], r["day"] = p["id"], p["day"]
            r.setdefault("roles", [])
            if not 1 <= r["line"] <= len(text) or not text[r["line"] - 1].strip():
                raise SystemExit(f"{s['id']}: bad line {r['line']}")
        s["reports"].sort(key=lambda r: (r["day"], r["post"]))
        s["first_day"] = s["reports"][0]["day"]
        state = {}
        for d in DAYS:
            rs = [r for r in s["reports"] if r["day"] <= d]
            if not rs:
                state[str(d)] = None
                continue
            figs = {}
            for r in rs:  # later reports overwrite earlier figures
                for k in FIG_KEYS:
                    if k in r:
                        figs[k] = r[k]
            for num, txt in (("missing", "missing_text"), ("houses", "houses_text")):
                if num in figs and txt in figs:
                    # a later word count ("dozens") supersedes an earlier number, and vice versa
                    last_num = max((i for i, r in enumerate(rs) if num in r), default=-1)
                    last_txt = max((i for i, r in enumerate(rs) if txt in r), default=-1)
                    figs.pop(num if last_txt > last_num else txt)
            rescue = None
            for r in rs:
                if "rescue" in r:
                    rescue = r["rescue"]
            state[str(d)] = dict(
                sev=max((r["sev"] for r in rs), key=SEV.get),
                red=any(r.get("red") for r in rs),
                rescue=rescue,
                roles=sorted({x for r in rs for x in r["roles"]}),
                figs=figs, n=len(rs), new=[r["post"] for r in rs if r["day"] == d],
            )
        s["state"] = state
        last = state[str(DAYS[-1])]
        s["sev"], s["roles"] = last["sev"], last["roles"]

    by_id = {s["id"]: s for s in SITES}
    pts = {**{k: v for k, v in extra_pts.items()}, **{s["id"]: s for s in SITES}}

    for inc in INCIDENTS:
        inc["post"] = post_of(inc["line"])["id"]
        if "between" in inc:
            a, b = (by_id.get(k) or extra_pts[k] for k in inc["between"])
            mid = Point((a["lon"] + b["lon"]) / 2, (a["lat"] + b["lat"]) / 2)
            near = roads[roads.distance(mid) < 0.03]
            if len(near):
                line = near.geometry.iloc[near.distance(mid).argmin()]
                mid = line.interpolate(line.project(mid))
            inc.update(lon=round(mid.x, 5), lat=round(mid.y, 5), match="approx")
        else:
            p = pts[inc["at"]]
            inc.update(lon=p["lon"], lat=p["lat"], match="approx" if "match_note" in inc else "exact")
    inc_by_id = {i["id"]: i for i in INCIDENTS}

    for r in RESCUE:
        p = by_id.get(r["at"]) or inc_by_id[r["at"]]
        r.update(lon=p["lon"], lat=p["lat"], post=post_of(r["line"])["id"], place=p["en"])
        if "frm" in r:
            f = by_id.get(r["frm"]) or inc_by_id[r["frm"]]
            r["frm_pt"] = [f["lon"], f["lat"]]
    for e in TIMELINE:
        e["post"] = post_of(e["line"])["id"]
        if e.get("site") and e["site"] not in by_id and e["site"] not in inc_by_id:
            raise SystemExit(f"timeline: unknown site {e['site']}")
    for q in QUOTES:
        q["post"] = post_of(q["line"])["id"]
        if not q.get("mm"):  # take the quoted words straight from the source line
            m = re.search(r'[“"](.+)[”"]', text[q["line"] - 1])
            if not m:
                raise SystemExit(f"quote at line {q['line']}: no quoted speech on that line")
            q["mm"] = m.group(1).strip()
        if norm(q["mm"])[:12] not in norm(text[q["line"] - 1]):
            raise SystemExit(f"quote at line {q['line']} does not match the source text")

    for p in posts:
        p["sites"] = [s["id"] for s in SITES if any(r["post"] == p["id"] for r in s["reports"])]
        p["incidents"] = [i["id"] for i in INCIDENTS if i["post"] == p["id"]]

    def facts_lines(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if (k == "line" or k.endswith("_line")) and isinstance(v, int):
                    yield v
                else:
                    yield from facts_lines(v)
        elif isinstance(o, list):
            for v in o:
                yield from facts_lines(v)
    for n in facts_lines(FACTS):
        if not 1 <= n <= len(text) or not text[n - 1].strip():
            raise SystemExit(f"facts: bad line {n}")
    for key in ("toll_29", "toll_01", "toll"):
        for t in FACTS[key]["places"]:
            if t["site"] not in by_id:
                raise SystemExit(f"{key}: unknown site {t['site']}")
        if sum(t.get("dead", 0) for t in FACTS[key]["places"]) != FACTS[key]["dead"]:
            raise SystemExit(f"{key}: places do not add up to the total")
    if sum(v["dead"] for v in FACTS["toll"]["by_ts"].values()) != FACTS["toll"]["dead"]:
        raise SystemExit("toll: townships do not add up to the total")
    for ts_name, v in FACTS["toll"]["by_ts"].items():
        if sum(t.get("dead", 0) for t in FACTS["toll"]["places"] if by_id[t["site"]]["ts"] == ts_name) != v["dead"]:
            raise SystemExit(f"toll: {ts_name} places do not add up to its reported total")

    for row in LIFELINES:
        for c in row["cells"].values():
            if not text[c["line"] - 1].strip():
                raise SystemExit(f"lifeline: bad line {c['line']}")
            c["post"] = post_of(c["line"])["id"]

    grades = {}
    for s in SITES:
        grades[s["match"]] = grades.get(s["match"], 0) + 1

    out = dict(
        source=dict(outlet="Dawei Watch", page="https://web.facebook.com/DaweiWatch",
                    days=["2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"], file=os.path.basename(SRC)),
        posts=posts, facts=FACTS, sites=SITES, references=REFERENCES, incidents=INCIDENTS,
        rescue=RESCUE, lifelines=dict(cols=LIFELINE_COLS, rows=LIFELINES), timeline=sorted(TIMELINE, key=lambda e: e["t"]), quotes=QUOTES,
        match_grades=grades,
    )
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"wrote {os.path.relpath(OUT)}: {len(posts)} posts, {len(SITES)} sites, {len(INCIDENTS)} incidents, "
          f"{len(TIMELINE)} timeline entries, {len(QUOTES)} quotes")
    print("match grades:", grades)
    for d in DAYS:
        on = [s for s in SITES if s["state"][str(d)]]
        print(f"  as of {d if d <= 30 else d - 30} {'Sep' if d <= 30 else 'Oct'}: {len(on)} sites, "
              + ", ".join(f"{k} {sum(1 for s in on if s['state'][str(d)]['sev'] == k)}"
                          for k in ("fatal", "severe", "affected")))


if __name__ == "__main__":
    main()
