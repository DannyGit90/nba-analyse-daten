# Datenquellen-Bestandspruefung

Pruefzeit UTC: 2026-11-21T21:13:13.472188+00:00
Quelle: https://basketball-data.billmill.org/nba/nba.duckdb
Ausfuehrung erfolgreich: True
Nur Tabellen/Spalten inventarisiert. Keine Spielerdaten importiert oder fachlich freigegeben.

## main.bbref_salaries
Suchhinweise: possible_player_identity, possible_player_team_link
Spalten: season (INTEGER), team_id (VARCHAR), bbref_id (VARCHAR), player_id (VARCHAR), salary (INTEGER)

## main.bbref_team_stats
Suchhinweise: keine
Spalten: season (INTEGER), team_id (VARCHAR), made_playoffs (BOOLEAN), g (INTEGER), min (DOUBLE), fgm (INTEGER), fga (INTEGER), fg_pct (DOUBLE), fg3m (INTEGER), fg3a (INTEGER), fg3_pct (DOUBLE), fg2m (INTEGER), fg2a (INTEGER), fg2_pct (DOUBLE), ftm (INTEGER), fta (INTEGER), ft_pct (DOUBLE), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), stl (INTEGER), blk (INTEGER), tov (INTEGER), pf (INTEGER), pts (INTEGER), opp_fgm (INTEGER), opp_fga (INTEGER), opp_fg_pct (DOUBLE), opp_fg3m (INTEGER), opp_fg3a (INTEGER), opp_fg3_pct (DOUBLE), opp_fg2m (INTEGER), opp_fg2a (INTEGER), opp_fg2_pct (DOUBLE), opp_ftm (INTEGER), opp_fta (INTEGER), opp_ft_pct (DOUBLE), opp_oreb (INTEGER), opp_dreb (INTEGER), opp_reb (INTEGER), opp_ast (INTEGER), opp_stl (INTEGER), opp_blk (INTEGER), opp_tov (INTEGER), opp_pf (INTEGER), opp_pts (INTEGER), age (DOUBLE), wins (INTEGER), losses (INTEGER), wins_pyth (INTEGER), losses_pyth (INTEGER), mov (DOUBLE), sos (DOUBLE), srs (DOUBLE), off_rtg (DOUBLE), def_rtg (DOUBLE), net_rtg (DOUBLE), pace (DOUBLE), fta_per_fga_pct (DOUBLE), fg3a_per_fga_pct (DOUBLE), ts_pct (DOUBLE), efg_pct (DOUBLE), tov_pct (DOUBLE), orb_pct (DOUBLE), ft_rate (DOUBLE), opp_efg_pct (DOUBLE), opp_tov_pct (DOUBLE), drb_pct (DOUBLE), opp_ft_rate (DOUBLE), arena_name (VARCHAR), attendance (INTEGER), attendance_per_g (INTEGER), avg_dist (DOUBLE), pct_fga_fg2a (DOUBLE), pct_fga_00_03 (DOUBLE), pct_fga_03_10 (DOUBLE), pct_fga_10_16 (DOUBLE), pct_fga_16_xx (DOUBLE), pct_fga_fg3a (DOUBLE), fg_pct_fg2a (DOUBLE), fg_pct_00_03 (DOUBLE), fg_pct_03_10 (DOUBLE), fg_pct_10_16 (DOUBLE), fg_pct_16_xx (DOUBLE), fg_pct_fg3a (DOUBLE), pct_ast_fg2 (DOUBLE), pct_ast_fg3 (DOUBLE), pct_fga_dunk (DOUBLE), fg_dunk (INTEGER), pct_fga_layup (DOUBLE), fg_layup (INTEGER), pct_fg3a_corner (DOUBLE), fg3_pct_corner (DOUBLE), fg3a_heave (INTEGER), fg3_heave (INTEGER), opp_avg_dist (DOUBLE), opp_pct_fga_fg2a (DOUBLE), opp_pct_fga_00_03 (DOUBLE), opp_pct_fga_03_10 (DOUBLE), opp_pct_fga_10_16 (DOUBLE), opp_pct_fga_16_xx (DOUBLE), opp_pct_fga_fg3a (DOUBLE), opp_fg_pct_fg2a (DOUBLE), opp_fg_pct_00_03 (DOUBLE), opp_fg_pct_03_10 (DOUBLE), opp_fg_pct_10_16 (DOUBLE), opp_fg_pct_16_xx (DOUBLE), opp_fg_pct_fg3a (DOUBLE), opp_pct_ast_fg2 (DOUBLE), opp_pct_ast_fg3 (DOUBLE), opp_pct_fga_dunk (DOUBLE), opp_fg_dunk (INTEGER), opp_pct_fga_layup (DOUBLE), opp_fg_layup (INTEGER), opp_pct_fg3a_corner (DOUBLE), opp_fg3_pct_corner (DOUBLE)

## main.betting_lines
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), provider_id (VARCHAR), provider (VARCHAR), home_team_id (VARCHAR), away_team_id (VARCHAR), open_spread (DOUBLE), open_total (DOUBLE), open_home_moneyline (INTEGER), open_away_moneyline (INTEGER), open_home_spread_odds (INTEGER), open_away_spread_odds (INTEGER), open_over_odds (INTEGER), open_under_odds (INTEGER), close_spread (DOUBLE), close_total (DOUBLE), close_home_moneyline (INTEGER), close_away_moneyline (INTEGER), close_home_spread_odds (INTEGER), close_away_spread_odds (INTEGER), close_over_odds (INTEGER), close_under_odds (INTEGER), espn_event_id (VARCHAR)

## main.ctg_team_summary
Suchhinweise: keine
Spalten: season (INTEGER), season_type (VARCHAR), team_id (VARCHAR), as_of_date (DATE), point_diff (DOUBLE), wins (INTEGER), losses (INTEGER), win_pct (DOUBLE), exp_wins_82 (DOUBLE), exp_wins (DOUBLE), win_diff (DOUBLE), off_rtg (DOUBLE), def_rtg (DOUBLE), spread_diff (DOUBLE), wins_last_2wk (INTEGER), losses_last_2wk (INTEGER), point_diff_last_2wk (DOUBLE), off_rtg_last_2wk (DOUBLE), def_rtg_last_2wk (DOUBLE), spread_diff_last_2wk (DOUBLE)

## main.epm
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (INTEGER), position (VARCHAR), rookie_year (INTEGER), height_inches (INTEGER), weight (INTEGER), gp (INTEGER), gs (INTEGER), roster_games (INTEGER), min (DOUBLE), min_per_game (DOUBLE), o_epm (DOUBLE), d_epm (DOUBLE), epm (DOUBLE), ewins (DOUBLE), usg_pct (DOUBLE), ts_pct (DOUBLE), efg_pct (DOUBLE), fg_pct_rim (DOUBLE), fg_pct_mid (DOUBLE), fg2_pct (DOUBLE), fg3_pct (DOUBLE), ft_pct (DOUBLE), oreb_pct (DOUBLE), dreb_pct (DOUBLE), ast_pct (DOUBLE), tov_pct (DOUBLE), stl_pct (DOUBLE), blk_pct (DOUBLE), fga_rim_per_75 (DOUBLE), fga_mid_per_75 (DOUBLE), fg3a_per_75 (DOUBLE), fta_per_75 (DOUBLE), fga_per_75 (DOUBLE)

## main.epm_daily
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), as_of_date (DATE), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (INTEGER), position (VARCHAR), rookie_year (INTEGER), height_inches (INTEGER), weight (INTEGER), gp (INTEGER), gs (INTEGER), roster_games (INTEGER), min (DOUBLE), min_per_game (DOUBLE), o_epm (DOUBLE), d_epm (DOUBLE), epm (DOUBLE), ewins (DOUBLE), usg_pct (DOUBLE), ts_pct (DOUBLE), efg_pct (DOUBLE), fg_pct_rim (DOUBLE), fg_pct_mid (DOUBLE), fg2_pct (DOUBLE), fg3_pct (DOUBLE), ft_pct (DOUBLE), oreb_pct (DOUBLE), dreb_pct (DOUBLE), ast_pct (DOUBLE), tov_pct (DOUBLE), stl_pct (DOUBLE), blk_pct (DOUBLE), fga_rim_per_75 (DOUBLE), fga_mid_per_75 (DOUBLE), fg3a_per_75 (DOUBLE), fta_per_75 (DOUBLE), fga_per_75 (DOUBLE)

## main.epm_predictive
Suchhinweise: possible_player_identity, possible_player_team_link
Spalten: season (INTEGER), as_of_date (DATE), player_id (VARCHAR), team_id (VARCHAR), age (INTEGER), position (VARCHAR), rookie_year (INTEGER), height_inches (INTEGER), weight (INTEGER), o_epm (DOUBLE), d_epm (DOUBLE), epm (DOUBLE), epm_change (DOUBLE), start_pct (DOUBLE), poss_per_48 (DOUBLE), min_per_48 (DOUBLE), usg_pct (DOUBLE), pts_per_100 (DOUBLE), ts_pct (DOUBLE), efg_pct (DOUBLE), fga_rim_per_100 (DOUBLE), fga_mid_per_100 (DOUBLE), fg2a_per_100 (DOUBLE), fg3a_per_100 (DOUBLE), fta_per_100 (DOUBLE), fg_pct_rim (DOUBLE), fg_pct_mid (DOUBLE), fg2_pct (DOUBLE), fg3_pct (DOUBLE), ft_pct (DOUBLE), ast_per_100 (DOUBLE), tov_per_100 (DOUBLE), oreb_per_100 (DOUBLE), dreb_per_100 (DOUBLE), stl_per_100 (DOUBLE), blk_per_100 (DOUBLE)

## main.epm_predictive_daily
Suchhinweise: possible_player_identity, possible_player_team_link
Spalten: season (INTEGER), as_of_date (DATE), player_id (VARCHAR), team_id (VARCHAR), age (INTEGER), position (VARCHAR), rookie_year (INTEGER), height_inches (INTEGER), weight (INTEGER), o_epm (DOUBLE), d_epm (DOUBLE), epm (DOUBLE), epm_change (DOUBLE), start_pct (DOUBLE), poss_per_48 (DOUBLE), min_per_48 (DOUBLE), usg_pct (DOUBLE), pts_per_100 (DOUBLE), ts_pct (DOUBLE), efg_pct (DOUBLE), fga_rim_per_100 (DOUBLE), fga_mid_per_100 (DOUBLE), fg2a_per_100 (DOUBLE), fg3a_per_100 (DOUBLE), fta_per_100 (DOUBLE), fg_pct_rim (DOUBLE), fg_pct_mid (DOUBLE), fg2_pct (DOUBLE), fg3_pct (DOUBLE), ft_pct (DOUBLE), ast_per_100 (DOUBLE), tov_per_100 (DOUBLE), oreb_per_100 (DOUBLE), dreb_per_100 (DOUBLE), stl_per_100 (DOUBLE), blk_per_100 (DOUBLE)

## main.espn_injuries
Suchhinweise: possible_player_identity, possible_player_team_link, possible_personnel_table_name
Spalten: season (INTEGER), fetched_at (TIMESTAMP WITH TIME ZONE), as_of_date (DATE), team_id (VARCHAR), player_id (VARCHAR), status (VARCHAR), fantasy_status (VARCHAR), injury_type (VARCHAR), location (VARCHAR), side (VARCHAR), detail (VARCHAR), return_date (DATE), updated_at (TIMESTAMP WITH TIME ZONE), short_comment (VARCHAR), long_comment (VARCHAR), espn_athlete_id (VARCHAR), espn_injury_id (VARCHAR)

## main.four_factors
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), team_id (VARCHAR), action_type (VARCHAR), o_scoring_poss (DOUBLE), o_poss (DOUBLE), o_pts_produced (DOUBLE), o_net_pts (DOUBLE)

## main.game_events
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link
Spalten: season (INTEGER), game_id (VARCHAR), action_id (INTEGER), action_number (INTEGER), period (INTEGER), time (DOUBLE), team_id (VARCHAR), person_id (VARCHAR), action_type (VARCHAR), sub_type (VARCHAR), description (VARCHAR), shot_result (VARCHAR), is_field_goal (BOOLEAN), shot_value (INTEGER), shot_distance (INTEGER), x (INTEGER), y (INTEGER), video_available (BOOLEAN), pts (INTEGER), home_team_id (VARCHAR), away_team_id (VARCHAR), home_score (INTEGER), away_score (INTEGER), matches_box_score (BOOLEAN)

## main.game_rotations
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link
Spalten: season (INTEGER), game_id (VARCHAR), team_id (VARCHAR), player_id (VARCHAR), period (INTEGER), in_time (DOUBLE), out_time (DOUBLE), pts (INTEGER), plus_minus (INTEGER), matches_box_score (BOOLEAN)

## main.games
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), game_date (DATE), game_type (VARCHAR), playoff_round (INTEGER), series_number (INTEGER), series_game (INTEGER), home_team_id (VARCHAR), away_team_id (VARCHAR), neutral_site (BOOLEAN)

## main.injury_report
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link, possible_personnel_table_name
Spalten: season (INTEGER), report_time (TIMESTAMP WITH TIME ZONE), game_id (VARCHAR), game_date (DATE), team_id (VARCHAR), player_id (VARCHAR), status (VARCHAR), reason (VARCHAR), detail (VARCHAR)

## main.metadata
Suchhinweise: keine
Spalten: dataset (VARCHAR), source (VARCHAR), first_season (INTEGER), last_season (INTEGER), seasons (INTEGER), updated (TIMESTAMP WITH TIME ZONE)

## main.net_pts_season
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), gp (INTEGER), min (DOUBLE), o_net_pts (DOUBLE), d_net_pts (DOUBLE), t_net_pts (DOUBLE), o_team_poss (DOUBLE), d_team_poss (DOUBLE), t_team_poss (DOUBLE)

## main.openrapm
Suchhinweise: possible_player_identity
Spalten: season (INTEGER), player_id (VARCHAR), built (DATE), possessions (INTEGER), o_rating (DOUBLE), d_rating (DOUBLE), rating (DOUBLE), wosa (DOUBLE), o_box_score (DOUBLE), o_on_court (DOUBLE), o_off_court (DOUBLE), o_team_sos (DOUBLE), o_box_adj (DOUBLE), d_box_score (DOUBLE), d_on_court (DOUBLE), d_off_court (DOUBLE), d_team_sos (DOUBLE), d_box_adj (DOUBLE)

## main.player_box
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link
Spalten: season (INTEGER), game_id (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), home (BOOLEAN), starter (BOOLEAN), played (BOOLEAN), seconds_played (INTEGER), d_avg_pos (DOUBLE), o_net_pts (DOUBLE), d_net_pts (DOUBLE), t_net_pts (DOUBLE), o_usg (DOUBLE), d_usg (DOUBLE), o_poss (DOUBLE), d_poss (DOUBLE), t_poss (DOUBLE), o_team_poss (DOUBLE), d_team_poss (DOUBLE), t_team_poss (DOUBLE), o_wpa (DOUBLE), d_wpa (DOUBLE), t_wpa (DOUBLE), fgm (INTEGER), fga (INTEGER), fg3m (INTEGER), fg3a (INTEGER), ftm (INTEGER), fta (INTEGER), layup_fgm (INTEGER), layup_fga (INTEGER), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), ast_fg3 (INTEGER), ast_layup (INTEGER), assisted_fgm (INTEGER), assisted_fg3m (INTEGER), assisted_layup_fgm (INTEGER), stl (INTEGER), blk (INTEGER), tov (INTEGER), live_tov (INTEGER), off_fouls (INTEGER), def_fouls (INTEGER), pts (INTEGER), plus_minus (INTEGER)

## main.player_details
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link
Spalten: season (INTEGER), game_id (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), action_type (VARCHAR), o_net_pts (DOUBLE), d_net_pts (DOUBLE), t_net_pts (DOUBLE)

## main.player_game_logs
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), game_id (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), opp_team_id (VARCHAR), game_date (DATE), home (BOOLEAN), win (BOOLEAN), min (DOUBLE), fgm (INTEGER), fga (INTEGER), fg_pct (DOUBLE), fg3m (INTEGER), fg3a (INTEGER), fg3_pct (DOUBLE), ftm (INTEGER), fta (INTEGER), ft_pct (DOUBLE), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), tov (INTEGER), stl (INTEGER), blk (INTEGER), blka (INTEGER), pf (INTEGER), pfd (INTEGER), pts (INTEGER), plus_minus (INTEGER), nba_fantasy_pts (DOUBLE), dd2 (INTEGER), td3 (INTEGER), wnba_fantasy_pts (DOUBLE), fp_high_score (DOUBLE), team_count (INTEGER), e_off_rating (DOUBLE), off_rating (DOUBLE), sp_work_off_rating (DOUBLE), e_def_rating (DOUBLE), def_rating (DOUBLE), sp_work_def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), sp_work_net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), dreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), e_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), usg_pct (DOUBLE), e_usg_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), sp_work_pace (DOUBLE), pie (DOUBLE), poss (INTEGER)

## main.player_game_status
Suchhinweise: possible_player_identity, possible_player_game_records, possible_player_team_link
Spalten: season (INTEGER), game_id (VARCHAR), team_id (VARCHAR), player_id (VARCHAR), starter (BOOLEAN), played (BOOLEAN), status (VARCHAR), reason (VARCHAR), comment (VARCHAR), in_box_score (BOOLEAN)

## main.player_season_stats
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (DOUBLE), gp (INTEGER), w (INTEGER), l (INTEGER), w_pct (DOUBLE), min (DOUBLE), fgm (INTEGER), fga (INTEGER), fg_pct (DOUBLE), fg3m (INTEGER), fg3a (INTEGER), fg3_pct (DOUBLE), ftm (INTEGER), fta (INTEGER), ft_pct (DOUBLE), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), tov (INTEGER), stl (INTEGER), blk (INTEGER), blka (INTEGER), pf (INTEGER), pfd (INTEGER), pts (INTEGER), plus_minus (INTEGER), nba_fantasy_pts (DOUBLE), dd2 (INTEGER), td3 (INTEGER), wnba_fantasy_pts (DOUBLE), fp_high_score (DOUBLE), team_count (INTEGER), def_rating (DOUBLE), dreb_pct (DOUBLE), pct_dreb (DOUBLE), pct_stl (DOUBLE), pct_blk (DOUBLE), opp_pts_off_tov (INTEGER), opp_pts_2nd_chance (INTEGER), opp_pts_fb (INTEGER), opp_pts_paint (INTEGER), def_ws (DOUBLE), def_ws_raw (DOUBLE), e_off_rating (DOUBLE), off_rating (DOUBLE), sp_work_off_rating (DOUBLE), e_def_rating (DOUBLE), sp_work_def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), sp_work_net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), e_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), usg_pct (DOUBLE), e_usg_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), sp_work_pace (DOUBLE), pie (DOUBLE), poss (INTEGER), player_last_team_id (VARCHAR), g (INTEGER), fga_frequency (DOUBLE), fg2a_frequency (DOUBLE), fg2m (INTEGER), fg2a (INTEGER), fg2_pct (DOUBLE), fg3a_frequency (DOUBLE), player_height (VARCHAR), player_height_inches (INTEGER), player_weight (INTEGER), country (VARCHAR), draft_year (INTEGER), draft_round (INTEGER), draft_number (INTEGER), college (VARCHAR)

## main.player_season_stats_per_100
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (DOUBLE), gp (INTEGER), w (INTEGER), l (INTEGER), w_pct (DOUBLE), min (DOUBLE), fgm (DOUBLE), fga (DOUBLE), fg_pct (DOUBLE), fg3m (DOUBLE), fg3a (DOUBLE), fg3_pct (DOUBLE), ftm (DOUBLE), fta (DOUBLE), ft_pct (DOUBLE), oreb (DOUBLE), dreb (DOUBLE), reb (DOUBLE), ast (DOUBLE), tov (DOUBLE), stl (DOUBLE), blk (DOUBLE), blka (DOUBLE), pf (DOUBLE), pfd (DOUBLE), pts (DOUBLE), plus_minus (DOUBLE), nba_fantasy_pts (DOUBLE), dd2 (INTEGER), td3 (INTEGER), wnba_fantasy_pts (DOUBLE), fp_high_score (DOUBLE), team_count (INTEGER), def_rating (DOUBLE), dreb_pct (DOUBLE), pct_dreb (DOUBLE), pct_stl (DOUBLE), pct_blk (DOUBLE), opp_pts_off_tov (DOUBLE), opp_pts_2nd_chance (DOUBLE), opp_pts_fb (DOUBLE), opp_pts_paint (DOUBLE), def_ws (DOUBLE), def_ws_raw (DOUBLE), e_off_rating (DOUBLE), off_rating (DOUBLE), sp_work_off_rating (DOUBLE), e_def_rating (DOUBLE), sp_work_def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), sp_work_net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), e_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), usg_pct (DOUBLE), e_usg_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), sp_work_pace (DOUBLE), pie (DOUBLE), poss (INTEGER), player_last_team_id (VARCHAR), g (INTEGER), fga_frequency (DOUBLE), fg2a_frequency (DOUBLE), fg2m (DOUBLE), fg2a (DOUBLE), fg2_pct (DOUBLE), fg3a_frequency (DOUBLE), player_height (VARCHAR), player_height_inches (INTEGER), player_weight (INTEGER), country (VARCHAR), draft_year (INTEGER), draft_round (INTEGER), draft_number (INTEGER), college (VARCHAR)

## main.player_season_stats_per_36
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (DOUBLE), gp (INTEGER), w (INTEGER), l (INTEGER), w_pct (DOUBLE), min (DOUBLE), fgm (DOUBLE), fga (DOUBLE), fg_pct (DOUBLE), fg3m (DOUBLE), fg3a (DOUBLE), fg3_pct (DOUBLE), ftm (DOUBLE), fta (DOUBLE), ft_pct (DOUBLE), oreb (DOUBLE), dreb (DOUBLE), reb (DOUBLE), ast (DOUBLE), tov (DOUBLE), stl (DOUBLE), blk (DOUBLE), blka (DOUBLE), pf (DOUBLE), pfd (DOUBLE), pts (DOUBLE), plus_minus (DOUBLE), nba_fantasy_pts (DOUBLE), dd2 (INTEGER), td3 (INTEGER), wnba_fantasy_pts (DOUBLE), fp_high_score (DOUBLE), team_count (INTEGER), def_rating (DOUBLE), dreb_pct (DOUBLE), pct_dreb (DOUBLE), pct_stl (DOUBLE), pct_blk (DOUBLE), opp_pts_off_tov (DOUBLE), opp_pts_2nd_chance (DOUBLE), opp_pts_fb (DOUBLE), opp_pts_paint (DOUBLE), def_ws (DOUBLE), def_ws_raw (DOUBLE), e_off_rating (DOUBLE), off_rating (DOUBLE), sp_work_off_rating (DOUBLE), e_def_rating (DOUBLE), sp_work_def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), sp_work_net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), e_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), usg_pct (DOUBLE), e_usg_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), sp_work_pace (DOUBLE), pie (DOUBLE), poss (INTEGER), player_last_team_id (VARCHAR), g (INTEGER), fga_frequency (DOUBLE), fg2a_frequency (DOUBLE), fg2m (DOUBLE), fg2a (DOUBLE), fg2_pct (DOUBLE), fg3a_frequency (DOUBLE), player_height (VARCHAR), player_height_inches (INTEGER), player_weight (INTEGER), country (VARCHAR), draft_year (INTEGER), draft_round (INTEGER), draft_number (INTEGER), college (VARCHAR)

## main.player_season_stats_per_game
Suchhinweise: possible_player_identity, possible_player_team_link, possible_playing_time
Spalten: season (INTEGER), season_type (VARCHAR), player_id (VARCHAR), team_id (VARCHAR), age (DOUBLE), gp (INTEGER), w (INTEGER), l (INTEGER), w_pct (DOUBLE), min (DOUBLE), fgm (DOUBLE), fga (DOUBLE), fg_pct (DOUBLE), fg3m (DOUBLE), fg3a (DOUBLE), fg3_pct (DOUBLE), ftm (DOUBLE), fta (DOUBLE), ft_pct (DOUBLE), oreb (DOUBLE), dreb (DOUBLE), reb (DOUBLE), ast (DOUBLE), tov (DOUBLE), stl (DOUBLE), blk (DOUBLE), blka (DOUBLE), pf (DOUBLE), pfd (DOUBLE), pts (DOUBLE), plus_minus (DOUBLE), nba_fantasy_pts (DOUBLE), dd2 (INTEGER), td3 (INTEGER), wnba_fantasy_pts (DOUBLE), fp_high_score (DOUBLE), team_count (INTEGER), def_rating (DOUBLE), dreb_pct (DOUBLE), pct_dreb (DOUBLE), pct_stl (DOUBLE), pct_blk (DOUBLE), opp_pts_off_tov (DOUBLE), opp_pts_2nd_chance (DOUBLE), opp_pts_fb (DOUBLE), opp_pts_paint (DOUBLE), def_ws (DOUBLE), def_ws_raw (DOUBLE), e_off_rating (DOUBLE), off_rating (DOUBLE), sp_work_off_rating (DOUBLE), e_def_rating (DOUBLE), sp_work_def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), sp_work_net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), e_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), usg_pct (DOUBLE), e_usg_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), sp_work_pace (DOUBLE), pie (DOUBLE), poss (INTEGER), player_last_team_id (VARCHAR), g (INTEGER), fga_frequency (DOUBLE), fg2a_frequency (DOUBLE), fg2m (DOUBLE), fg2a (DOUBLE), fg2_pct (DOUBLE), fg3a_frequency (DOUBLE), player_height (VARCHAR), player_height_inches (INTEGER), player_weight (INTEGER), country (VARCHAR), draft_year (INTEGER), draft_round (INTEGER), draft_number (INTEGER), college (VARCHAR)

## main.player_seasons
Suchhinweise: possible_player_identity
Spalten: season (INTEGER), player_id (VARCHAR), name (VARCHAR), played (BOOLEAN)

## main.players
Suchhinweise: possible_player_identity
Spalten: player_id (VARCHAR), name (VARCHAR), first_season (INTEGER), last_season (INTEGER)

## main.rosters_daily
Suchhinweise: possible_player_identity, possible_player_team_link, possible_personnel_table_name
Spalten: season (INTEGER), as_of_date (DATE), team_id (VARCHAR), player_id (VARCHAR), num (VARCHAR), position (VARCHAR), two_way (BOOLEAN), how_acquired (VARCHAR)

## main.schedule
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), game_date (DATE), start_time (TIMESTAMP WITH TIME ZONE), game_type (VARCHAR), playoff_round (INTEGER), series_number (INTEGER), series_game (INTEGER), home_team_id (VARCHAR), away_team_id (VARCHAR), neutral_site (BOOLEAN), status (VARCHAR), status_text (VARCHAR), label (VARCHAR), sub_label (VARCHAR), subtype (VARCHAR), series_text (VARCHAR), if_necessary (BOOLEAN), arena_name (VARCHAR), arena_city (VARCHAR), arena_state (VARCHAR)

## main.team_box
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), team_id (VARCHAR), home (BOOLEAN), win (BOOLEAN), seconds_played (INTEGER), poss (DOUBLE), opp_poss (DOUBLE), opp_pts (INTEGER), efg_pct (DOUBLE), fg2_pct (DOUBLE), fg3_pct (DOUBLE), ft_rate (DOUBLE), fg2_net_pts (DOUBLE), fg3_net_pts (DOUBLE), shooting_net_pts (DOUBLE), turnover_net_pts (DOUBLE), rebound_net_pts (DOUBLE), freethrow_net_pts (DOUBLE), pts_allowed_off_live_tov (INTEGER), n_times_pts_allowed_off_live_tov (INTEGER), fgm (INTEGER), fga (INTEGER), fg3m (INTEGER), fg3a (INTEGER), ftm (INTEGER), fta (INTEGER), layup_fgm (INTEGER), layup_fga (INTEGER), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), ast_fg3 (INTEGER), ast_layup (INTEGER), assisted_fgm (INTEGER), assisted_fg3m (INTEGER), assisted_layup_fgm (INTEGER), stl (INTEGER), blk (INTEGER), tov (INTEGER), live_tov (INTEGER), off_fouls (INTEGER), def_fouls (INTEGER), pts (INTEGER)

## main.team_epm
Suchhinweise: keine
Spalten: season (INTEGER), as_of_date (DATE), team_id (VARCHAR), is_projection (BOOLEAN), epm (DOUBLE), o_epm (DOUBLE), d_epm (DOUBLE), epm_change_10g (DOUBLE), sos (DOUBLE), o_sos (DOUBLE), d_sos (DOUBLE), sos_games (INTEGER)

## main.team_epm_daily
Suchhinweise: keine
Spalten: season (INTEGER), as_of_date (DATE), team_id (VARCHAR), is_projection (BOOLEAN), epm (DOUBLE), o_epm (DOUBLE), d_epm (DOUBLE), epm_change_10g (DOUBLE), sos (DOUBLE), o_sos (DOUBLE), d_sos (DOUBLE), sos_games (INTEGER)

## main.team_game_logs
Suchhinweise: keine
Spalten: season (INTEGER), game_id (VARCHAR), team_id (VARCHAR), opp_team_id (VARCHAR), game_date (DATE), home (BOOLEAN), win (BOOLEAN), min (DOUBLE), fgm (INTEGER), fga (INTEGER), fg_pct (DOUBLE), fg3m (INTEGER), fg3a (INTEGER), fg3_pct (DOUBLE), ftm (INTEGER), fta (INTEGER), ft_pct (DOUBLE), oreb (INTEGER), dreb (INTEGER), reb (INTEGER), ast (INTEGER), tov (INTEGER), stl (INTEGER), blk (INTEGER), blka (INTEGER), pf (INTEGER), pfd (INTEGER), pts (INTEGER), plus_minus (INTEGER), e_off_rating (DOUBLE), off_rating (DOUBLE), e_def_rating (DOUBLE), def_rating (DOUBLE), e_net_rating (DOUBLE), net_rating (DOUBLE), ast_pct (DOUBLE), ast_to (DOUBLE), ast_ratio (DOUBLE), oreb_pct (DOUBLE), dreb_pct (DOUBLE), reb_pct (DOUBLE), tm_tov_pct (DOUBLE), efg_pct (DOUBLE), ts_pct (DOUBLE), e_pace (DOUBLE), pace (DOUBLE), pace_per40 (DOUBLE), poss (INTEGER), pie (DOUBLE), team_oreb (INTEGER)

## main.team_openrapm
Suchhinweise: keine
Spalten: season (INTEGER), through_date (DATE), built (DATE), ready (BOOLEAN), team_id (VARCHAR), games (INTEGER), o_rating (DOUBLE), d_rating (DOUBLE), rating (DOUBLE), o_recent (DOUBLE), d_recent (DOUBLE), recent (DOUBLE)

## main.team_openrapm_daily
Suchhinweise: keine
Spalten: season (INTEGER), through_date (DATE), built (DATE), ready (BOOLEAN), team_id (VARCHAR), games (INTEGER), o_rating (DOUBLE), d_rating (DOUBLE), rating (DOUBLE), o_recent (DOUBLE), d_recent (DOUBLE), recent (DOUBLE)

## main.team_seasons
Suchhinweise: keine
Spalten: season (INTEGER), team_id (VARCHAR), nba_abbrev (VARCHAR), full_name (VARCHAR), is_nba (BOOLEAN), conference (VARCHAR), division (VARCHAR), cup_group (VARCHAR)

Naechster Schritt: gefundene Kandidaten gezielt mit echten Datensaetzen auf Identitaet, Einsatzdaten und Zeitbezug pruefen. Keine Verfuegbarkeit allein aus Spaltennamen ableiten.
