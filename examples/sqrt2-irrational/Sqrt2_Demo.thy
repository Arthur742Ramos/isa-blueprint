theory Sqrt2_Demo
  imports Main "HOL.Rat"
begin

text \<open>
  Skeleton theory backing the sqrt2-irrational blueprint. The proved nodes carry
  genuine proofs; the named node is left as a draft (\<open>sorry\<close>); the missing
  node has no counterpart yet.
\<close>

lemma even_square:
  fixes n :: nat
  assumes "even (n * n)"
  shows "even n"
  using assms by simp

lemma lowest_terms:
  fixes r :: rat
  shows "\<exists>p q. q \<noteq> 0 \<and> coprime p q \<and> r = of_int p / of_int q"
  using quotient_of_div [of r]
  by (metis quotient_of_coprime quotient_of_nonzero of_int_0_eq_iff)

lemma even_numerator:
  fixes p q :: int
  assumes "coprime p q" and "p * p = 2 * (q * q)"
  shows "even p"
proof -
  have "even (p * p)" using assms(2) by simp
  thus "even p" by simp
qed

lemma even_denominator:
  fixes p q :: int
  assumes "coprime p q" and "p * p = 2 * (q * q)"
  shows "even q"
  sorry

end
