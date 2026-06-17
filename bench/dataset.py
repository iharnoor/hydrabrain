"""
hydrabrain benchmark dataset.

A 19-"page" personal-memory corpus (an intercultural relationship timeline) plus
19 gold-labelled retrieval test cases spanning extraction, multi-hop reasoning,
temporal/entity-direction reasoning, negation, and aggregation.

This is the stand-in for the real goal: a personal second brain over everything
you consume (Instagram, YouTube, articles...). The corpus is dense, temporal,
and entity-heavy — exactly the regime where pure vector search breaks down and a
graph-native store should win.

NOTE: This file is auto-assembled from the source corpus; it is intentionally
dependency-free (no chromadb / pymupdf imports) so it can be imported anywhere.
"""

from dataclasses import dataclass

TIMELINE_CHUNKS = [
    (
        "This document chronicles the relationship journey of Harnoor Singh and Katie, "
        "from their second meeting in October 2020 through buying a car together in May 2022. "
        "It covers 18 key moments across 19 months, including holidays, cultural exchanges, "
        "family introductions, travel milestones, and shared firsts. "
        "The timeline captures how an intercultural couple - Harnoor from India and Katie from "
        "the United States - built a relationship that bridged two cultures, with both partners "
        "actively embracing each other's traditions and families."
    ),
    (
        "October 18, 2020 - Meeting for the Second Time: "
        "Harnoor and Katie met for the second time on October 18, 2020. "
        "They had first connected earlier that month through mutual friends at Florida State University. "
        "This was still very early in their relationship - they were just getting to know each other. "
        "They spent the evening hanging out outdoors, lying on the grass and taking a playful upside-down selfie together. "
        "It was a casual, lighthearted meetup that marked the real beginning of their story. "
        "At this point, neither of them had a car, so getting around Tallahassee required planning."
    ),
    (
        "November 2, 2020 - First Car Date: "
        "On November 2, 2020, Harnoor and Katie went on their first car date. "
        "Katie was driving, and Harnoor sat in the passenger seat. This was a meaningful moment "
        "because it was one of their first real dates outside of campus. They drove around "
        "Tallahassee, exploring the area together. The Synovus bank building is visible through "
        "the windshield. Katie was a confident driver and Harnoor was clearly enjoying the ride. "
        "This was about two weeks after they met for the second time, showing how quickly "
        "they were spending more time together. They were both FSU students at the time."
    ),
    (
        "December 23, 2020 - Harnoor's Birthday Celebration: "
        "Katie surprised Harnoor with a birthday celebration on December 23, 2020. "
        "This was their first birthday together as a couple - they had only been dating for about "
        "two months at this point. Katie got him a large blue 'Happy Birthday' gift bag. "
        "They celebrated at what appears to be Harnoor's apartment in Tallahassee. "
        "Harnoor was wearing his signature leather jacket and glasses, and looked genuinely surprised and happy. "
        "This birthday marked an important early milestone - Katie putting effort into making "
        "the day special showed the relationship was becoming serious. It was also winter break "
        "at FSU, so the fact that they stayed in Tallahassee to celebrate together was meaningful."
    ),
    (
        "January 1, 2021 - Traveling to Miami, New Year's Trip: "
        "On January 1, 2021, Harnoor and Katie traveled to Miami together to ring in the New Year. "
        "This photo was taken at the airport while waiting for their flight. They were sitting by a large "
        "American flag mural in the terminal, with Katie working on a laptop. "
        "This was their first trip together as a couple - a huge relationship milestone. "
        "They had been dating for about two and a half months at this point. "
        "Harnoor was wearing a white T-shirt with a graphic print and his glasses, "
        "while Katie had her hair down. The airport was busy with other New Year travelers. "
        "They were both excited about their first vacation together, heading to South Beach."
    ),
    (
        "February 14, 2021 - First Valentine's Day Dinner: "
        "Harnoor and Katie celebrated their first Valentine's Day together on February 14, 2021. "
        "They went to an upscale restaurant in Tallahassee for a romantic dinner date. "
        "Both were dressed up nicely - Katie wore an elegant navy off-shoulder dress, and "
        "Harnoor wore a dark blazer over a black shirt. They were seated at a wooden table "
        "with wine glasses and water. The restaurant had a warm ambiance with artwork on the walls "
        "and a colorful decorative piece nearby. This was about four months into their relationship, "
        "and it was the first time they did a formal, dressed-up date night. "
        "It represented a shift from casual college hangouts to more intentional, romantic dates."
    ),
    (
        "March 16, 2021 - Katie's Birthday: "
        "Harnoor celebrated Katie's birthday on March 16, 2021. He got her a beautiful white "
        "layered birthday cake that read 'Happy Birthday Katie' with chocolate and cream decorations. "
        "They celebrated at what appears to be Katie's family home or a friend's house - a warm kitchen "
        "setting with wooden cabinets. Harnoor was wearing his glasses and a black hoodie, and both were "
        "beaming with happiness behind the cake. This was significant because it was the first time "
        "Harnoor celebrated Katie's birthday, reciprocating the effort she had made for his birthday "
        "back in December 2020. They had now been together for about five months. "
        "The homemade celebration feel showed their comfort with each other's personal spaces."
    ),
    (
        "April 19, 2021 - Revisiting the Place of Their First Date: "
        "On April 19, 2021, Harnoor and Katie went back to the location of their very first date. "
        "They stood on a stone bridge overlooking a scenic river or lake surrounded by lush green trees. "
        "Harnoor wore a maroon FSU T-shirt and a light blue jacket, while Katie wore a green striped top. "
        "Revisiting their first date spot about six months later was a nostalgic and romantic gesture. "
        "The scenery was beautiful - it was spring in Florida with everything in full bloom. "
        "This trip back to where it all started showed that they were reflecting on how far "
        "they had come as a couple. The location appears to be a park or nature area near Tallahassee "
        "that held special sentimental value for both of them."
    ),
    (
        "May 30, 2021 - First Beach Trip to FSU: "
        "On May 30, 2021, Harnoor and Katie took a photo together in front of the iconic "
        "Westcott Building and fountain at Florida State University. This was described as their "
        "'first beach trip to FSU' - likely combining a visit to a nearby Florida beach with a stop "
        "at their university campus. Harnoor was wearing casual shorts and a T-shirt with a backpack, "
        "while Katie wore a striped top. The Westcott Building with its distinctive red brick architecture "
        "and twin towers is the most recognizable landmark at FSU. The fountain was flowing on a "
        "beautiful sunny day with palm trees and blue skies. This was about seven months into their "
        "relationship, and they were now well-established as a couple on campus. "
        "FSU held deep meaning for them as the place where they first met."
    ),
    (
        "July 3, 2021 - Visiting Princeton University: "
        "On July 3, 2021, Harnoor and Katie visited Princeton University in New Jersey. "
        "They took a selfie on the Princeton campus with its iconic Gothic stone buildings "
        "and manicured green lawns in the background. They were accompanied by a friend - "
        "a young woman in a red top. This was a summer road trip or vacation, showing they were "
        "now traveling beyond Florida together. Harnoor wore a blue T-shirt and a rain jacket, "
        "and Katie was in a black top. The sky was overcast. Visiting an Ivy League campus together "
        "during the summer suggested they were exploring the East Coast, possibly visiting friends "
        "or family in the Northeast. This was their first trip together outside of Florida, "
        "about eight months into the relationship."
    ),
    (
        "July 4, 2021 - Fourth of July Fireworks Celebration: "
        "Harnoor and Katie celebrated the Fourth of July 2021 together, watching fireworks "
        "in a large crowd. The night sky was lit up with fireworks behind them as they took a selfie. "
        "Harnoor wore a blue polo shirt and Katie was smiling brightly. The crowd around them was "
        "large and festive, with many people holding up phones to capture the fireworks. "
        "This appears to have been a major public fireworks display, possibly in New Jersey or "
        "the East Coast area since they were visiting Princeton the day before. "
        "Celebrating America's Independence Day together was especially meaningful for Harnoor "
        "as an international student from India experiencing this American tradition with Katie. "
        "This was one of several holidays they spent together in 2021."
    ),
    (
        "August 21, 2021 - Attending Their First American Wedding Together: "
        "On August 21, 2021, Harnoor and Katie attended their first American wedding together. "
        "The wedding was at a beautiful outdoor venue with rose gardens, mountain views, and elegant "
        "landscaping. Katie wore a stunning navy blue polka-dot dress, and Harnoor was in a sharp "
        "navy blue suit. They looked like a picture-perfect couple. This was a significant cultural "
        "milestone for Harnoor - attending an American wedding for the first time. Coming from India, "
        "where weddings are multi-day colorful celebrations, experiencing an American outdoor garden "
        "wedding was a new and exciting experience. Going to a wedding together as a couple also "
        "signaled a deeper level of commitment - they were now being invited to important life events "
        "as a unit. They had been together for about ten months at this point."
    ),
    (
        "October 15, 2021 - Celebrating Navratri Together: "
        "On October 15, 2021, Harnoor and Katie celebrated Navratri together - a major Hindu festival. "
        "They both dressed in traditional Indian attire and held dandiya sticks for the Garba dance. "
        "Katie wore a beautiful red and green lehenga with traditional jewelry, fully embracing Indian culture. "
        "Harnoor wore a teal kurta. A banner behind them reads 'HOL RAJ' (likely part of a larger festival banner). "
        "This was incredibly significant - Katie, who is American, fully participated in Harnoor's Indian "
        "cultural traditions. She didn't just attend; she dressed up in full traditional attire and danced Garba. "
        "This showed deep respect and enthusiasm for Harnoor's heritage. For Harnoor, seeing his girlfriend "
        "embrace his culture must have been deeply meaningful. They had been together for about a year. "
        "This was likely organized by the Indian student community at FSU or in the Tallahassee area."
    ),
    (
        "November 25, 2021 - Thanksgiving with Katie's Family: "
        "Harnoor spent Thanksgiving with Katie's family on November 25, 2021. "
        "They sat around a dining table with a traditional Thanksgiving spread - turkey, ham, "
        "cranberries, sides, and other dishes. Katie's father and sister (or another family member) "
        "were also at the table. This was a major relationship milestone - meeting and spending a "
        "holiday with the partner's family. For Harnoor, as an international student from India, "
        "Thanksgiving was not a holiday he grew up with, so experiencing it with an American family "
        "was culturally significant. The warm, homey setting with natural light coming through the windows "
        "showed a comfortable family gathering. Katie and Harnoor had now been together for over a year, "
        "and being included in family holidays showed strong acceptance from Katie's side of the family."
    ),
    (
        "December 25, 2021 - Christmas Together: "
        "Harnoor and Katie celebrated Christmas together on December 25, 2021. "
        "They posed by a decorated Christmas tree with lights and ornaments. Harnoor wore a gray jacket "
        "over a red shirt, and Katie wore a white top with jeans. This was their second Christmas together "
        "(the first being in 2020, early in the relationship), but this time they had been together for "
        "over a year and were much more established as a couple. The cozy indoor setting with holiday "
        "decorations - garland along the wall, the lit tree - showed a warm holiday celebration. "
        "For Harnoor, who grew up celebrating Diwali and other Indian festivals, Christmas with Katie "
        "represented their ongoing cultural exchange. Katie celebrated Navratri with him in October; "
        "now he was celebrating Christmas with her in December. This mutual cultural sharing "
        "was a defining feature of their relationship."
    ),
    (
        "January 1, 2022 - New Year's in Miami, South Beach: "
        "Harnoor and Katie rang in the New Year of 2022 on South Beach in Miami. "
        "They took a selfie on Ocean Drive with the iconic Art Deco buildings and palm trees behind them. "
        "Katie wore a turquoise 'Royal Beach' tank top, and Harnoor was in a casual outfit. "
        "This was their second New Year's trip to Miami - they had also traveled there on January 1, 2021, "
        "exactly one year earlier. Making it an annual tradition showed the consistency and growth of their "
        "relationship. Comparing the two Miami trips: in 2021 they were a brand new couple (2.5 months), "
        "and now in 2022 they were a seasoned couple (over 14 months together). "
        "The Boulevard Hotel is visible in the background. The weather was sunny and warm, "
        "typical of a Miami winter day."
    ),
    (
        "March 3, 2022 - Packing for India Trip: "
        "On March 3, 2022, Harnoor and Katie packed their suitcases for a trip to India. "
        "They posed in their apartment with multiple large suitcases - blue and gray - ready for the journey. "
        "This was a monumental milestone in their relationship. Katie was about to visit India for the first "
        "time, and more importantly, she was going to meet Harnoor's family. For an intercultural couple, "
        "the 'meeting the parents' trip to the other country is one of the biggest steps. "
        "They had been together for about a year and a half at this point. The apartment looked like a "
        "typical college/post-college setup with a kitchen counter visible. The amount of luggage suggested "
        "a long trip - likely several weeks in India. Harnoor was wearing his glasses and a green striped shirt, "
        "while Katie wore a plaid flannel. They both looked excited and a bit nervous for the big trip."
    ),
    (
        "March 2022 - Visiting the Taj Mahal in India: "
        "During their India trip in March 2022, Harnoor and Katie visited the Taj Mahal in Agra. "
        "Katie wore a beautiful turquoise traditional Indian salwar kameez, and Harnoor wore a light blue "
        "button-down shirt. The iconic white marble Taj Mahal is visible in the background with its famous "
        "gardens and reflecting pools. This was a dream-come-true moment - visiting one of the Seven Wonders "
        "of the World together. For Katie, this was her first time in India and seeing the Taj Mahal in person. "
        "For Harnoor, showing Katie his home country and its most famous landmark was deeply personal. "
        "Katie fully embraced wearing Indian clothing during the trip, just as she had done for Navratri "
        "back in October 2021. The trip to India represented the deepest level of cultural immersion in their "
        "relationship - Katie wasn't just learning about Indian culture from afar, she was living it. "
        "They also met Harnoor's family during this trip, who warmly welcomed Katie."
    ),
    (
        "May 7, 2022 - Buying a Car Together, Tesla Model 3: "
        "On May 7, 2022, Harnoor and Katie bought a car together - a white Tesla Model 3. "
        "They posed at the Tesla dealership with a Tesla employee who was handing over the keys. "
        "Harnoor wore a gray blazer and Katie stood beside him. This was one of the biggest financial "
        "and practical commitments they made as a couple. Buying a car together signified long-term planning "
        "and shared responsibility. They had been together for about a year and seven months. "
        "Choosing a Tesla showed their interest in technology and sustainability. "
        "Looking back at the timeline: in November 2020 they went on their 'first car date' in someone else's car, "
        "and now in May 2022 they were buying their own car together. That progression from borrowing a car "
        "to co-owning a Tesla captured the growth of their relationship. "
        "The Tesla was white, and the dealership parking lot had charging stations visible in the background."
    ),
]


@dataclass
class TestCase:
    category: str
    name: str
    question: str
    expected: str
    why_matters: str
    # gold_keywords: a chunk is a "hit" if ALL keywords in at least one
    # gold group appear in it.  Groups are OR'd, keywords within a group
    # are AND'd.  e.g. [["Princeton", "New Jersey"], ["Taj Mahal"]]
    # means a chunk is relevant if it mentions (Princeton AND New Jersey)
    # OR (Taj Mahal).
    gold_keywords: list[list[str]] = None  # set via field default_factory below

    def __post_init__(self):
        if self.gold_keywords is None:
            self.gold_keywords = []



TEST_CASES = [
    # ── Information Extraction ────────────────────────────
    TestCase(
        category="Information Extraction",
        name="Specific date recall",
        question="When did Harnoor and Katie meet for the second time?",
        expected="October 18, 2020",
        why_matters="Exact date retrieval from a specific memory",
        gold_keywords=[["October 18, 2020", "second time"]],
    ),
    TestCase(
        category="Information Extraction",
        name="Buried detail in rich context",
        question="What car did Harnoor and Katie buy together?",
        expected="White Tesla Model 3",
        why_matters="Specific fact (car model + color) buried in descriptive paragraph",
        gold_keywords=[["Tesla Model 3"]],
    ),
    TestCase(
        category="Information Extraction",
        name="Cultural detail extraction",
        question="What did Katie wear for Navratri?",
        expected="Red and green lehenga with traditional jewelry",
        why_matters="Specific clothing detail from a cultural event description",
        gold_keywords=[["lehenga", "Navratri"]],
    ),

    # ── Multi-Session Reasoning ───────────────────────────
    TestCase(
        category="Multi-Session Reasoning",
        name="Synthesize relationship progression",
        question="How did Harnoor and Katie's relationship progress from casual dating to major commitments?",
        expected="First car date Nov 2020 → first formal dinner Valentine's 2021 → bought a Tesla together May 2022",
        why_matters="Requires combining 3+ memories to show relationship arc",
        # Need at least 2 of these 3 chunks in top-5
        gold_keywords=[["first car date"], ["Valentine"], ["Tesla"]],
    ),
    TestCase(
        category="Multi-Session Reasoning",
        name="Cross-cultural exchange pattern",
        question="How did Harnoor and Katie embrace each other's cultures?",
        expected="Katie: Navratri/lehenga/Garba, wore Indian clothing at Taj Mahal. Harnoor: Thanksgiving with Katie's family, Christmas together.",
        why_matters="Must combine cultural exchange moments across multiple memories",
        gold_keywords=[["Navratri", "lehenga"], ["Thanksgiving", "Katie's family"], ["Taj Mahal"]],
    ),

    # ── Temporal Reasoning ────────────────────────────────
    TestCase(
        category="Temporal Reasoning",
        name="Timeline ordering — counting repeated events",
        question="How many times did Harnoor and Katie go to Miami for New Year's?",
        expected="Twice — January 2021 and January 2022",
        why_matters="Must identify a repeated event across two different years",
        # Both Miami NYE chunks must appear
        gold_keywords=[["January 1, 2021", "Miami"], ["January 1, 2022", "Miami"]],
    ),
    TestCase(
        category="Temporal Reasoning",
        name="First trip outside Florida",
        question="When was Harnoor and Katie's first trip outside of Florida?",
        expected="July 3, 2021 — Princeton University visit in New Jersey",
        why_matters="Must distinguish Florida trips from out-of-state trips",
        gold_keywords=[["Princeton", "New Jersey"]],
    ),

    # ── Semantic Understanding ────────────────────────────
    TestCase(
        category="Semantic Understanding",
        name="Relationship milestone inference",
        question="What was the significance of Harnoor and Katie attending a wedding together?",
        expected="It signaled deeper commitment — being invited to important life events as a unit",
        why_matters="Must infer emotional/relational meaning, not just recall facts",
        gold_keywords=[["wedding", "commitment"]],
    ),
    TestCase(
        category="Semantic Understanding",
        name="Intercultural significance",
        question="Why was the Fourth of July celebration special for Harnoor?",
        expected="As an international student from India, experiencing this American tradition with Katie was culturally meaningful",
        why_matters="Must extract the cultural significance, not just 'they watched fireworks'",
        gold_keywords=[["Fourth of July", "international student"]],
    ),

    # ── Abstention / Precision ────────────────────────────
    TestCase(
        category="Abstention",
        name="Don't confuse similar events",
        question="When is Harnoor's birthday and how was it celebrated?",
        expected="December 23 — Katie surprised him with a blue gift bag at his apartment",
        why_matters="Must NOT confuse Harnoor's birthday with Katie's birthday",
        gold_keywords=[["December 23", "Harnoor's Birthday"]],
    ),
    TestCase(
        category="Abstention",
        name="Don't hallucinate engagement",
        question="Are Harnoor and Katie engaged or married?",
        expected="Unknown / not mentioned — buying a car is the biggest commitment mentioned",
        why_matters="Should NOT infer engagement/marriage from buying a car together",
        # The overview doc is the safest retrieval — no wedding/engagement signal
        gold_keywords=[["chronicles the relationship journey"]],
    ),

    # ── Negation (Vector DBs Can't "NOT") ─────────────────
    TestCase(
        category="Negation",
        name="Negation — not a birthday",
        question="What did Harnoor and Katie celebrate together that was NOT a birthday?",
        expected="Navratri, July 4th, Valentine's Day, Thanksgiving, Christmas, New Year's, wedding",
        why_matters="Vector search returns birthday chunks FIRST because 'birthday' is in the query — cosine similarity can't negate",
        # Any non-birthday celebration chunk counts as a hit
        gold_keywords=[["Navratri"], ["Fourth of July"], ["Valentine"], ["Thanksgiving"], ["Christmas Together"], ["wedding"]],
    ),
    TestCase(
        category="Negation",
        name="Negation — trips outside Florida",
        question="What trips did Harnoor and Katie take that were NOT in Florida?",
        expected="Princeton/NJ (July 2021), India (March 2022)",
        why_matters="Vector returns Miami and FSU trips (highest similarity to 'trip') even though they're IN Florida",
        gold_keywords=[["Princeton", "New Jersey"], ["Taj Mahal", "India"]],
    ),

    # ── Temporal Adjacency ────────────────────────────────
    TestCase(
        category="Temporal Adjacency",
        name="Day-after reasoning",
        question="What did Harnoor and Katie do the day after visiting Princeton?",
        expected="July 4th fireworks celebration — they watched fireworks in a large crowd",
        why_matters="Vector search has no concept of 'the day after' — returns Princeton chunk or random travel chunks",
        gold_keywords=[["Fourth of July", "fireworks"]],
    ),
    TestCase(
        category="Temporal Adjacency",
        name="Chronological ordering of milestones",
        question="Put these events in chronological order: buying a car, visiting India, attending a wedding",
        expected="Wedding (Aug 2021) → India (March 2022) → Tesla (May 2022)",
        why_matters="Vector returns chunks in SIMILARITY order, not chronological — embeddings have no clock",
        # All 3 event chunks must be in top 5
        gold_keywords=[["wedding"], ["Taj Mahal"], ["Tesla"]],
    ),

    # ── Entity Direction (WHO did WHAT to WHOM) ───────────
    TestCase(
        category="Entity Direction",
        name="Directional gift giving",
        question="What did Katie specifically do for Harnoor's birthday?",
        expected="Surprised him with a large blue 'Happy Birthday' gift bag at his apartment on December 23, 2020",
        why_matters="Vector returns both birthday chunks equally — can't distinguish Katie→Harnoor from Harnoor→Katie direction",
        gold_keywords=[["December 23", "Katie surprised"]],
    ),
    TestCase(
        category="Entity Direction",
        name="One-directional cultural adoption",
        question="Which of Harnoor's Indian traditions did Katie participate in?",
        expected="Navratri (wore lehenga, danced Garba), wore Indian clothing at Taj Mahal",
        why_matters="Vector also returns Thanksgiving/Christmas (Harnoor adopting Katie's traditions) — can't filter by direction",
        gold_keywords=[["Navratri", "lehenga"], ["Taj Mahal", "Indian"]],
    ),

    # ── Geographic Entity Filtering ───────────────────────
    TestCase(
        category="Geographic Filtering",
        name="International vs domestic",
        question="Which events happened outside of the United States?",
        expected="Only the India trip — visiting the Taj Mahal in March 2022",
        why_matters="Vector returns any travel chunk (Miami, Princeton, India all score similarly on 'events outside') — no geographic entity awareness",
        gold_keywords=[["Taj Mahal", "India"]],
    ),

    # ── Aggregation Across All Chunks ─────────────────────
    TestCase(
        category="Aggregation",
        name="Exhaustive listing",
        question="List every holiday or celebration Harnoor and Katie shared together",
        expected="Harnoor's birthday, Katie's birthday, NYE 2021, NYE 2022, Valentine's Day, Navratri, July 4th, Thanksgiving, Christmas, wedding attendance",
        why_matters="Vector top-5 retrieval returns ~5 most 'celebration-like' chunks and misses the rest — can't aggregate across all 19 memories",
        # Each distinct celebration chunk is a gold group
        gold_keywords=[
            ["Harnoor's Birthday"], ["Katie's Birthday"], ["Miami", "2021"],
            ["Miami", "2022"], ["Valentine"], ["Navratri"],
            ["Fourth of July"], ["Thanksgiving"], ["Christmas Together"], ["wedding"],
        ],
    ),
]


PAGES = TIMELINE_CHUNKS
