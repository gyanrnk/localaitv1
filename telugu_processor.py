import re

FILLER_PATTERNS = [
    r'ఈ విషయంలో మరిన్ని వివరాలు రానున్నాయి[.।]*',
    r'మరిన్ని వివరాలు రానున్నాయి[.।]*',
    r'వివరాలు రానున్నాయి[.।]*',
    r'అప్డేట్లు రానున్నాయి[.।]*',
    r'సమాచారం రానున్నది[.।]*',
]


class TeluguProcessor:
    """Process Telugu text and convert numbers / abbreviations into more natural Telugu/TTS-friendly text."""

    ONES = ['', 'ఒకటి', 'రెండు', 'మూడు', 'నాలుగు', 'అయిదు', 'ఆరు', 'ఏడు', 'ఎనిమిది', 'తొమ్మిది']
    TENS = ['', 'పది', 'ఇరవై', 'ముప్పై', 'నలభై', 'యాభై', 'అరవై', 'డెబ్బై', 'ఎనభై', 'తొంభై']
    TEENS = [
        'పది', 'పదకొండు', 'పన్నెండు', 'పదమూడు', 'పద్నాలుగు',
        'పదిహేను', 'పదహారు', 'పదిహేడు', 'పద్దెనిమిది', 'పందొమ్మిది'
    ]

    COMMON_ABBREVIATIONS = {
        'Dr.': 'డాక్టర్',
        'Mr.': 'మిస్టర్',
        'Mrs.': 'మిసెస్',
        'Ms.': 'మిస్',
        'Prof.': 'ప్రొఫెసర్',
        'St.': 'సెయింట్',
        'Sr.': 'సీనియర్',
        'Jr.': 'జూనియర్',
    }

    def __init__(self):
        pass

    def number_to_telugu(self, num: int) -> str:
        """
        Convert an integer to Telugu words.
        Examples:
            1000 -> ఒక వెయ్యి
            2000 -> రెండు వేలు
            2008 -> రెండు వేల ఎనిమిది
        """
        if num == 0:
            return 'సున్నా'

        if num < 0:
            return 'మైనస్ ' + self.number_to_telugu(-num)

        if num >= 10000000:  # Crores
            crores = num // 10000000
            remainder = num % 10000000
            result = self.number_to_telugu(crores) + ' కోట్లు'
            if remainder > 0:
                result += ' ' + self.number_to_telugu(remainder)
            return result

        if num >= 100000:  # Lakhs
            lakhs = num // 100000
            remainder = num % 100000
            result = self.number_to_telugu(lakhs) + ' లక్షలు'
            if remainder > 0:
                result += ' ' + self.number_to_telugu(remainder)
            return result

        if num >= 1000:  # Thousands
            thousands = num // 1000
            remainder = num % 1000

            # 1000 -> ఒక వెయ్యి
            if thousands == 1 and remainder == 0:
                return 'ఒక వెయ్యి'

            # Round thousands: 2000, 3000, 4000...
            if remainder == 0:
                return self.number_to_telugu(thousands) + ' వేలు'

            # Non-round thousands: 2008, 3456...
            if thousands == 1:
                return 'వెయ్యి ' + self.number_to_telugu(remainder)

            return self.number_to_telugu(thousands) + ' వేల ' + self.number_to_telugu(remainder)

        if num >= 100:  # Hundreds
            hundreds = num // 100
            remainder = num % 100

            if hundreds == 1:
                result = 'నూట'
            else:
                result = self.ONES[hundreds] + ' వందల'

            if remainder > 0:
                result += ' ' + self.number_to_telugu(remainder)

            return result

        if num >= 20:  # Tens
            tens = num // 10
            ones = num % 10
            result = self.TENS[tens]
            if ones > 0:
                result += ' ' + self.ONES[ones]
            return result

        if num >= 10:  # Teens
            return self.TEENS[num - 10]

        return self.ONES[num]

    def convert_numbers_in_text(self, text: str) -> str:
        """
        Convert all numeric sequences in text to Telugu words.
        """
        def replace_number(match: re.Match) -> str:
            num_str = match.group(0).replace(',', '')
            try:
                num = int(num_str)
                return self.number_to_telugu(num)
            except ValueError:
                return match.group(0)

        pattern = r'\d+(?:,\d+)*'
        return re.sub(pattern, replace_number, text)

    def expand_common_abbreviations(self, text: str) -> str:
        """
        Expand common abbreviations such as Dr. -> డాక్టర్.
        """
        for abbr, full_form in self.COMMON_ABBREVIATIONS.items():
            text = re.sub(rf'\b{re.escape(abbr)}', full_form, text)
        return text

    def expand_acronyms(self, text: str) -> str:
        """
        Spell out acronyms letter-by-letter.
        Examples:
            DMK -> d m k
            BJP -> b j p
            D.M.K. -> d m k
        """

        def replace_dotted_acronym(match: re.Match) -> str:
            token = match.group(0)
            letters = re.findall(r'[A-Za-z]', token)
            return ' '.join(letter.lower() for letter in letters)

        def replace_plain_acronym(match: re.Match) -> str:
            token = match.group(0)
            return ' '.join(letter.lower() for letter in token)

        # First handle dotted acronyms like D.M.K.
        text = re.sub(r'\b(?:[A-Z]\.){2,}[A-Z]?\.?', replace_dotted_acronym, text)

        # Then handle plain all-caps acronyms like DMK
        text = re.sub(r'\b[A-Z]{2,}\b', replace_plain_acronym, text)

        return text

    def remove_media_references(self, text: str) -> str:
        """
        Remove anchor phrases that reference the video/clip itself.
        Examples: "ఈ వీడియోలో", "ఈ క్లిప్‌లో", etc.
        """
        patterns = [
            # Telugu script patterns
            r'ఈ\s+వీడియోలో[\s,]*',
            r'ఈ\s+క్లిప్[\s్లో,]*',
            r'ఈ\s+దృశ్యంలో[\s,]*',
            r'వీడియోలో\s+చూడవచ్చు[\s,]*',
            r'వీడియో\s+లో[\s,]*',
            r'క్లిప్\s+లో[\s,]*',
            r'ఈ\s+వీడియో\s+ద్వారా[\s,]*',
            r'కింది\s+వీడియోలో[\s,]*',
            r'పై\s+వీడియోలో[\s,]*',

            # Romanised / mixed patterns
            r'\bee\s+video\s+lo\b[\s,]*',
            r'\byah\s+clip\s+lo\b[\s,]*',
            r'\bvideo\s+lo\b[\s,]*',
            r'\bclip\s+lo\b[\s,]*',
            r'\bclip\s+లో\b[\s,]*',
            r'\bvideo\s+లో\b[\s,]*',
            r'\bclip\s+లో\s+చూడవచ్చు[\s,]*',
            r'\bvideo\s+లో\s+చూడవచ్చు[\s,]*',
        ]

        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        text = re.sub(r'\s{2,}', ' ', text)
        text = re.sub(r'^[\s,।]+|[\s,]+$', '', text)
        return text.strip()

    def clean_script(self, script: str) -> str:
        """
        Clean the script by removing unwanted phrases and extra spacing.
        """
        unwanted_phrases = [
            'ఈ రోజు వార్తలు',
            'శుభ రాత్రి',
            'శుభోదయం',
            'ధన్యవాదాలు',
            'ఒక గంట క్రితం',
            'రాత్రి వార్తలు',
            'ఉదయం వార్తలు',
            'మధ్యాహ్నం వార్తలు',
        ]

        result = script

        for phrase in unwanted_phrases:
            result = result.replace(phrase, '')

        for pattern in FILLER_PATTERNS:
            result = re.sub(pattern, '', result).strip()

        result = re.sub(r'\n\s*\n', '\n\n', result)
        result = re.sub(r'[ \t]+', ' ', result)
        result = re.sub(r'\s+([,.।!?])', r'\1', result)
        result = re.sub(r'\s{2,}', ' ', result)

        return result.strip()

    def preprocess_text(self, text: str) -> str:
        """
        Full preprocessing pipeline:
        1. Remove media references
        2. Expand common abbreviations like Dr.
        3. Expand acronyms like DMK -> d m k
        4. Convert numbers to Telugu words
        5. Clean extra filler / spacing
        """
        text = self.remove_media_references(text)
        text = self.expand_common_abbreviations(text)
        text = self.expand_acronyms(text)
        text = self.convert_numbers_in_text(text)
        text = self.clean_script(text)
        return text