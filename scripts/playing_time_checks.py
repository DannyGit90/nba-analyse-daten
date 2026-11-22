"""Pure minutes/seconds comparison core. No source fetch or unit/model approval."""
import math
from collections import Counter, defaultdict
from decimal import Decimal, localcontext

KEY_FIELDS = ('season','game_id','player_id','team_id')


def valid_minutes(value):
    if type(value) not in (int,float):return False
    try:return math.isfinite(value) and value>=0
    except OverflowError:return False


def compare_values(minutes, seconds):
    result={'status':'invalid_value','minutes_input_repr':repr(minutes),'seconds_input_repr':repr(seconds),
        'invalid_fields':[],'seconds_from_minutes_decimal':None,'delta_seconds_decimal':None,
        'float_roundtrip_matches':None,'units_verified':False,'model_input_approved':False,'betting_release':False}
    if not valid_minutes(minutes):result['invalid_fields'].append('min')
    if type(seconds) is not int or not 0<=seconds<=2147483647:
        result['invalid_fields'].append('seconds_played')
    if result['invalid_fields']:return result
    m=Decimal(str(minutes));s=Decimal(seconds)
    precision=max(40,max(m.adjusted()+2,s.adjusted())-min(m.as_tuple().exponent,0)+5)
    with localcontext() as context:
        context.prec=precision
        converted=m*Decimal(60);delta=converted-s
    roundtrip=type(minutes) is float and minutes==seconds/60
    status='decimal_value_match' if delta==0 else 'float_roundtrip_match' if roundtrip else 'observed_difference'
    result.update(status=status,seconds_from_minutes_decimal=str(converted),
        delta_seconds_decimal='0' if delta==0 else str(delta),float_roundtrip_matches=roundtrip)
    return result


def row_key(row):
    if not isinstance(row,dict) or type(row.get('season')) is not int:return None
    for field in KEY_FIELDS[1:]:
        value=row.get(field)
        if not isinstance(value,str) or not value or value!=value.strip():return None
    return tuple(row[field] for field in KEY_FIELDS)


def compare_rows(log_rows, box_rows):
    if not isinstance(log_rows,list) or not isinstance(box_rows,list):raise ValueError('Input row lists required')
    groups={'logs':defaultdict(list),'box':defaultdict(list)};invalid=[]
    for side,records in (('logs',log_rows),('box',box_rows)):
        for i,row in enumerate(records,1):
            key=row_key(row)
            if key is None:invalid.append({'side':side,'row_index':i,'status':'invalid_key'})
            else:groups[side][key].append(row)
    output=[]
    for key in sorted(set(groups['logs'])|set(groups['box'])):
        left=groups['logs'].get(key,[]);right=groups['box'].get(key,[])
        record={'key':dict(zip(KEY_FIELDS,key)),'log_row_count':len(left),'box_row_count':len(right)}
        if len(left)>1 or len(right)>1:record['status']='ambiguous_key'
        elif not left:record['status']='missing_log_row'
        elif not right:record['status']='missing_box_row'
        else:record.update(compare_values(left[0].get('min'),right[0].get('seconds_played')))
        output.append(record)
    return {'schema':'playing-time-comparison-v1','hypothesis':'player_game_logs.min * 60 equals player_box.seconds_played',
        'input_log_rows':len(log_rows),'input_box_rows':len(box_rows),'records':output,
        'invalid_key_rows':invalid,'status_counts':dict(Counter(r['status'] for r in output)),
        'units_verified':False,'model_input_approved':False,'betting_release':False,
        'limitations':['Only supplied rows are compared; no population quality or coverage claim.',
            'No game completion, source freshness or historical as-of availability is verified by this core.',
            'Decimal comparison uses the decimal text representation of supplied numeric values.',
            'Float roundtrip equality tests only minutes == integer_seconds / 60 under Python float arithmetic; it is not source precision verification.',
            'No tolerance, rounding to agreement, zero-filling, deduplication or cartesian matching is applied.',
            'An observed difference is not automatically a source error. Zero or absent rows do not establish health, injury or playing status.',
            'seconds_played is required to fit the inventoried INTEGER type. Overtime is not rejected by a 48-minute cap.']}
