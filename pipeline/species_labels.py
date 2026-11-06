"""Parrotfish colour forms represented as three combined training labels."""
PARROTFISH_GENERA={'Scarus','Sparisoma','Cryptotomus','Nicholsina','Calotomus','Chlorurus','Cetoscarus','Bolbometopon','Hipposcarus','Leptoscarus'}
TAGS={'juvenile':'J','initial':'IP','terminal':'TP'}
def parrotfish(item):return item.get('family','').lower()=='scaridae' or item.get('scientific_name','').split(' ')[0] in PARROTFISH_GENERA
def title(item):return item.get('display_name',item.get('scientific_name','—'))
def expand(catalog):
    output={}
    for key,item in catalog.items():
        if item.get('base_species_id') or not parrotfish(item):output[key]=item;continue
        for tag in ('TP','IP','J'):
            output[key+'__'+tag]={**item,'base_species_id':key,'display_name':item['scientific_name']+' ['+tag+']'}
    return output
