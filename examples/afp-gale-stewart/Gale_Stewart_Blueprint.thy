theory Gale_Stewart_Blueprint
  imports "GaleStewart_Games.GaleStewartDeterminedGames"
begin

text \<open>
  A thin local corollary built directly on top of the Archive of Formal
  Proofs entry \<open>GaleStewart_Games\<close>.  It restates the headline determinacy
  result for the empty position so the blueprint can reference a fact that
  this example owns, while still depending on the real AFP development.
\<close>

context closed_GSgame
begin

corollary closed_game_determinacy:
  "winning_position_Even [] \<or> winning_position_Odd []"
  using every_game_is_determined .

end

end
