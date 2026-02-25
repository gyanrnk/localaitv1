"""
Telugu Processor - Handles Telugu text processing
Converts numbers to Telugu words
"""
import re


class TeluguProcessor:
    """Process Telugu text and convert numbers to words"""
    
    ONES = ['', 'ఒకటి', 'రెండు', 'మూడు', 'నాలుగు', 'అయిదు', 'ఆరు', 'ఏడు', 'ఎనిమిది', 'తొమ్మిది']
    TENS = ['', 'పది', 'ఇరవై', 'ముప్పై', 'నలభై', 'యాభై', 'అరవై', 'డెబ్బై', 'ఎనభై', 'తొంభై']
    TEENS = ['పది', 'పదకొండు', 'పన్నెండు', 'పదమూడు', 'పద్నాలుగు', 'పదిహేను', 
             'పదహారు', 'పదిహేడు', 'పద్దెనిమిది', 'పందొమ్మిది']
    
    def __init__(self):
        pass
    
    def number_to_telugu(self, num: int) -> str:
        """
        Convert a number to Telugu words
        
        Args:
            num: Integer number to convert
            
        Returns:
            Telugu word representation
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
            result = self.number_to_telugu(thousands) + ' వేలు'
            if remainder > 0:
                result += ' ' + self.number_to_telugu(remainder)
            return result
        
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
        Convert all numbers in text to Telugu words
        
        Args:
            text: Input text with numbers
            
        Returns:
            Text with numbers converted to Telugu
        """
        def replace_number(match):
            num_str = match.group(0)
            num_str = num_str.replace(',', '')
            try:
                num = int(num_str)
                return self.number_to_telugu(num)
            except ValueError:
                return num_str
        
        pattern = r'\d+(?:,\d+)*'
        result = re.sub(pattern, replace_number, text)
        
        return result
    
    def clean_script(self, script: str) -> str:
        """
        Clean the script by removing unwanted phrases
        
        Args:
            script: Input script
            
        Returns:
            Cleaned script
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
        
        result = re.sub(r'\n\s*\n', '\n\n', result)
        result = result.strip()
        
        return result
