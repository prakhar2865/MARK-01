import re
from datetime import datetime

KNOWN_NATIONALITIES = {
    'INDIAN':'Indian','INDIA':'Indian','IND':'Indian',
    'AMERICAN':'American','USA':'American','UNITED STATES':'American',
    'BRITISH':'British','UK':'British','UNITED KINGDOM':'British',
    'CANADIAN':'Canadian','AUSTRALIAN':'Australian','NEPALESE':'Nepalese',
    'BHUTANESE':'Bhutanese','BANGLADESHI':'Bangladeshi','PAKISTANI':'Pakistani',
    'SRI LANKAN':'Sri Lankan','SINGAPOREAN':'Singaporean','MALAYSIAN':'Malaysian',
}

def _joined(lines): return '\n'.join(x.strip() for x in lines if x and x.strip())
def _clean(v): return re.sub(r'\s+', ' ', v).strip(' :#-') if v else None

def extract_nationality_enhanced(lines, document_type=None):
    text=_joined(lines)
    # labelled field first
    for pat in [r'\bNATIONALITY\s*[:#-]?\s*([A-Za-z ]{3,30})', r'\bCITIZENSHIP\s*[:#-]?\s*([A-Za-z ]{3,30})']:
        m=re.search(pat,text,re.I)
        if m:
            val=_clean(m.group(1)); val=re.split(r'\b(?:PASSPORT|SEX|GENDER|DATE|DOB|NAME|NUMBER|VALID|ADDRESS)\b',val,1,flags=re.I)[0].strip()
            for k,v in KNOWN_NATIONALITIES.items():
                if k.lower() in val.lower() or val.lower()==v.lower(): return v
    upper=text.upper()
    for k,v in KNOWN_NATIONALITIES.items():
        if re.search(r'\b'+re.escape(k)+r'\b',upper): return v
    return None

def extract_gender(lines, document_type=None):
    text=_joined(lines)
    patterns=[r'\b(?:SEX|GENDER)\s*[:#-]?\s*(MALE|FEMALE|M|F|OTHER)\b', r'\b(MALE|FEMALE)\b']
    for pat in patterns:
        m=re.search(pat,text,re.I)
        if m:
            v=m.group(1).upper(); return {'M':'Male','F':'Female','MALE':'Male','FEMALE':'Female','OTHER':'Other'}.get(v,v.title())
    return None

def extract_passport_fields(lines):
    text=_joined(lines)
    number=None
    # MRZ passport number: second MRZ line starts document type/country then number
    for line in lines:
        s=re.sub(r'\s+','',line.upper())
        m=re.search(r'\b([A-Z]\d{7})\b',s)
        if m: number=m.group(1); break
        m=re.search(r'\b([A-Z0-9]{8,9})\b',s)
        if m and re.search('[A-Z]',m.group(1)) and re.search(r'\d',m.group(1)): number=m.group(1); break
    nationality=extract_nationality_enhanced(lines,'Passport')
    gender=extract_gender(lines,'Passport')
    return {'passport_number':number,'nationality':nationality,'gender':gender}

def extract_visa_fields(lines):
    text=_joined(lines)
    def grab(pattern):
        m=re.search(pattern,text,re.I); return _clean(m.group(1)) if m else None
    visa_number=grab(r'\b(?:VISA\s*(?:NO|NUMBER)|VISA\s*ID)\s*[:#-]?\s*([A-Z0-9][A-Z0-9-]{4,20})')
    visa_type=grab(r'\b(?:VISA\s*TYPE|TYPE\s*OF\s*VISA)\s*[:#-]?\s*([A-Za-z][A-Za-z -]{2,30})')
    entry=grab(r'\b(?:ENTRY|ENTRIES|NO\.?\s*OF\s*ENTRIES)\s*[:#-]?\s*([A-Za-z0-9 -]{1,20})')
    stay=grab(r'\b(?:DURATION|STAY|DURATION\s*OF\s*STAY)\s*[:#-]?\s*(\d{1,3}\s*(?:DAYS?|MONTHS?|YEARS?))')
    return {'visa_number':visa_number,'visa_type':visa_type,'entry_type':entry,'stay_duration':stay}

def validate_visa_fields(fields):
    findings=[]; checks=[]; valid=True
    num=fields.get('visa_number')
    if num:
        checks.append({'field':'visa_number','status':'VALID','reason':'Visa number format extracted.'})
    else:
        checks.append({'field':'visa_number','status':'MISSING','reason':'Visa number not detected.'}); valid=False
    if fields.get('entry_type'):
        e=fields['entry_type'].lower()
        status='VALID' if any(x in e for x in ('single','multiple','double','1','2')) else 'REVIEW'
        checks.append({'field':'entry_type','status':status,'reason':'Visa entry information extracted.'})
    if fields.get('stay_duration'):
        m=re.search(r'(\d+)',fields['stay_duration']); n=int(m.group(1)) if m else 0
        status='VALID' if 1<=n<=3650 else 'INVALID'; valid &= status=='VALID'
        checks.append({'field':'stay_duration','status':status,'reason':'Visa stay duration checked.'})
    else:
        checks.append({'field':'stay_duration','status':'MISSING','reason':'Stay duration not detected.'})
    return {'status':'VALID' if valid else 'REVIEW','checks':checks,'findings':findings}
