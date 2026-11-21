"""Reconstructed observed numeric blocks plus synthetic guards; not full saved ESPN responses."""
import copy
import datetime as dt
import unittest
from unittest.mock import Mock
from daily_review import collect as old_collect
from espn_line_import import collect_lines, normalize


class EspnLineTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 11, 20, 21, 59, 44, tzinfo=dt.timezone.utc)
        self.f = {'game_id':'0022600043','home':'ATL','away':'CHA','start_time_utc':'2026-11-21T00:00:00Z'}
        self.block = {'provider':{'name':'DraftKings'},'overUnder':218.5,'spread':-7.5,
            'moneyline':{'home':{'close':{'odds':'-249'},'open':{'odds':'-212'}},
                         'away':{'close':{'odds':'+205'},'open':{'odds':'+177'}}},
            'pointSpread':{'home':{'close':{'line':'-7.5','odds':'-108'},'open':{'line':'-5.5','odds':'-110'}},
                           'away':{'close':{'line':'+7.5','odds':'-112'},'open':{'line':'+5.5','odds':'-110'}}},
            'total':{'over':{'close':{'odds':'-115'},'open':{'odds':'-106'}},
                     'under':{'close':{'odds':'-105'},'open':{'odds':'-114'}}}}

    def event(self, f, block):
        return {'date':f['start_time_utc'],'status':{'type':{'state':'pre'}},'competitions':[{
            'date':f['start_time_utc'],'competitors':[
            {'homeAway':'home','team':{'abbreviation':f['home']}},
            {'homeAway':'away','team':{'abbreviation':f['away']}}],'odds':[block]}]}

    def run_block(self, block=None):
        return collect_lines({'forecasts':[self.f]},self.now,
                             lambda url:{'events':[self.event(self.f,block or self.block)]})

    def test_observed_atlanta_six_selections(self):
        rows,errors=self.run_block()
        self.assertEqual((len(rows),errors),(6,[]))
        spread={r['side']:r for r in rows if r['market']=='spread'}
        self.assertEqual((spread['home']['line'],spread['away']['line']),(-7.5,7.5))
        self.assertAlmostEqual(spread['home']['odds'],1+100/108)
        self.assertEqual(spread['home']['line_field'],'pointSpread.home.close.line')
        self.assertEqual(next(r for r in rows if r['market']=='total')['line'],218.5)

    def test_three_observed_numeric_shapes_six_to_eighteen(self):
        fixtures=[self.f,dict(self.f,game_id='0022600044',home='BKN',away='ORL'),
                  dict(self.f,game_id='0022600045',home='CLE',away='IND')]
        blocks=[copy.deepcopy(self.block) for _ in fixtures]
        for b,values in zip(blocks[1:],[(223.5,6.5,'+217','-264','-108','-112','-111','-109'),
                                      (234.5,-5.5,'-230','+191','-118','-102','-107','-113')]):
            total,line,hm,am,hs,aws,over,under=values
            b['overUnder']=total;b['spread']=line
            b['moneyline']['home']['close']['odds']=hm;b['moneyline']['away']['close']['odds']=am
            for side,ln,price in [('home',line,hs),('away',-line,aws)]:
                b['pointSpread'][side]['close']={'line':str(ln),'odds':price}
            b['total']['over']['close']['odds']=over;b['total']['under']['close']['odds']=under
        payload={'events':[self.event(f,b) for f,b in zip(fixtures,blocks)]}
        p={'forecasts':fixtures}
        self.assertEqual(len(old_collect(p,self.now,lambda u:payload)[0]),6)
        self.assertEqual(len(collect_lines(p,self.now,lambda u:payload)[0]),18)

    def test_legacy_block_unchanged(self):
        b={'provider':{'name':'DraftKings'},'details':'ATL -7.5',
           'homeTeamOdds':{'moneyLine':-249,'spreadOdds':-108},
           'awayTeamOdds':{'moneyLine':205,'spreadOdds':-112},
           'overUnder':218.5,'overOdds':-115,'underOdds':-105}
        self.assertEqual(normalize(b,self.f),(b,[],[]))
        self.assertEqual(len(self.run_block(b)[0]),6)

    def test_open_only_not_imported(self):
        b=copy.deepcopy(self.block)
        for group in ('pointSpread','total'):
            for side in b[group].values():side.pop('close')
        self.assertEqual(len(self.run_block(b)[0]),2)

    def test_bad_spread_only_blocks_spread(self):
        b=copy.deepcopy(self.block);b['pointSpread']['away']['close']['line']='8.5'
        rows,errors=self.run_block(b)
        self.assertEqual({r['market'] for r in rows},{'moneyline','total'})
        self.assertTrue(any(e.get('market')=='spread' for e in errors))

    def test_bad_total_only_blocks_total(self):
        for value in [None,True,0,float('inf')]:
            b=copy.deepcopy(self.block);b['overUnder']=value
            with self.subTest(value=value):
                self.assertEqual({r['market'] for r in self.run_block(b)[0]},{'moneyline','spread'})

    def test_conflicting_legacy_price_rejected(self):
        b=copy.deepcopy(self.block);b['overOdds']=-110
        rows,errors=self.run_block(b)
        self.assertFalse(any(r['market']=='total' for r in rows))
        self.assertTrue(errors)

    def test_conflicting_legacy_line_rejected(self):
        b=copy.deepcopy(self.block);b['homeTeamOdds']={'spreadOdds':-108};b['details']='ATL -5.5'
        self.assertFalse(any(r['market']=='spread' for r in self.run_block(b)[0]))

    def test_equal_legacy_and_nested_not_duplicated(self):
        b=copy.deepcopy(self.block);b.update(details='ATL -7.5',overOdds=-115,underOdds=-105,
            homeTeamOdds={'spreadOdds':-108},awayTeamOdds={'spreadOdds':-112})
        self.assertEqual(len(self.run_block(b)[0]),6)

    def test_close_total_line_must_agree(self):
        b=copy.deepcopy(self.block);b['total']['over']['close']['line']='o219.5'
        self.assertFalse(any(r['market']=='total' for r in self.run_block(b)[0]))
        b['total']['over']['close']['line']='o218.5'
        self.assertEqual(len(self.run_block(b)[0]),6)

    def test_invalid_spread_price_does_not_use_open(self):
        for value in [True,'56%','nan',99]:
            b=copy.deepcopy(self.block);b['pointSpread']['home']['close']['odds']=value
            with self.subTest(value=value):
                self.assertFalse(any(r['market']=='spread' for r in self.run_block(b)[0]))

    def test_boolean_line_rejected(self):
        b=copy.deepcopy(self.block);b['pointSpread']['home']['close']['line']=True
        self.assertFalse(any(r['market']=='spread' for r in self.run_block(b)[0]))

    def test_one_request_and_input_preserved(self):
        payload={'events':[self.event(self.f,self.block)]};before=copy.deepcopy(payload)
        loader=Mock(return_value=payload)
        collect_lines({'forecasts':[self.f]},self.now,loader)
        loader.assert_called_once();self.assertEqual(payload,before)

    def test_flags_and_unknown_price_time_preserved(self):
        for r in self.run_block()[0]:
            self.assertFalse(r['betting_release']);self.assertFalse(r['rules_verified'])
            self.assertIsNone(r['price_timestamp_utc'])
            self.assertEqual(r['price_status'],'indirect_reference_time_unknown')

    def test_started_game_excluded(self):
        self.f['start_time_utc']=self.now.isoformat()
        self.assertEqual(self.run_block()[0],[])

    def test_mismatched_teams_excluded(self):
        p={'forecasts':[dict(self.f,home='CLE')]}
        self.assertEqual(collect_lines(p,self.now,lambda u:{'events':[self.event(self.f,self.block)]})[0],[])

    def test_missing_nested_price_not_invented(self):
        b=copy.deepcopy(self.block);b['total']['under']['close'].pop('odds')
        rows,_=self.run_block(b)
        self.assertEqual(len([r for r in rows if r['market']=='total']),1)


if __name__=='__main__':unittest.main()
