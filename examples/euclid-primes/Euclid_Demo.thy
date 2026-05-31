theory Euclid_Demo
  imports "HOL-Computational_Algebra.Primes"
begin

text \<open>
  Skeleton theory backing the euclid-primes blueprint. The lower lemmas carry
  genuine proofs; the obligation near the top is drafted with \<open>sorry\<close>, and the
  final theorem is left for future work (no counterpart here).
\<close>

abbreviation euclid_number :: "nat \<Rightarrow> nat" where
  "euclid_number n \<equiv> fact n + 1"

lemma dvd_factorial:
  fixes k n :: nat
  assumes "0 < k" and "k \<le> n"
  shows "k dvd fact n"
  using assms by (simp add: dvd_fact)

lemma prime_divisor:
  fixes m :: nat
  assumes "1 < m"
  shows "\<exists>p. prime p \<and> p dvd m"
  using assms prime_factor_nat [of m] by auto

lemma prime_gt_bound:
  fixes n p :: nat
  assumes "prime p" and "p dvd euclid_number n"
  shows "p > n"
  sorry

end
