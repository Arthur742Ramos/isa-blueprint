theory FTA_Demo
  imports "HOL-Computational_Algebra.Primes"
    "HOL-Library.Multiset"
begin

text \<open>
  Skeleton theory for the fundamental-theorem-of-arithmetic blueprint.

  The definitions and the two helper lemmas (\<open>dvd_prime\<close>,
  \<open>prime_divisor\<close>) are discharged using the library, the existence
  theorem is stated (named, not yet proved), and the remaining obligations are
  left as \<^bold>\<open>sorry\<close> so the blueprint can track them as agent tasks.
\<close>

subsection \<open>Definitions\<close>

text \<open>Primality and the product over a multiset come straight from the
  library; we re-export them under local names so the blueprint ids resolve.\<close>

abbreviation prime_nat :: "nat \<Rightarrow> bool"
  where "prime_nat p \<equiv> prime p"

abbreviation prod_mset_nat :: "nat multiset \<Rightarrow> nat"
  where "prod_mset_nat M \<equiv> prod_mset M"

text \<open>A prime factorization of \<open>n\<close> is a multiset of primes whose product
  is \<open>n\<close>.\<close>

definition prime_factorization_of :: "nat \<Rightarrow> nat multiset \<Rightarrow> bool"
  where "prime_factorization_of n M \<longleftrightarrow>
           (\<forall>p \<in># M. prime p) \<and> prod_mset M = n"

subsection \<open>Helper lemmas (formalised)\<close>

lemma dvd_prime:
  assumes "prime (p::nat)" and "p dvd a * b"
  shows "p dvd a \<or> p dvd b"
  using assms by (simp add: prime_dvd_mult_iff)

lemma prime_divisor:
  assumes "1 < (m::nat)"
  shows "\<exists>p. prime p \<and> p dvd m"
  using assms prime_factor_nat[of m] by auto

subsection \<open>Open obligations (tracked by the blueprint)\<close>

text \<open>A prime dividing a product of primes is one of them.  Ready for an
  agent: it only depends on \<open>dvd_prime\<close>.\<close>

lemma prime_dvd_prod_mset:
  assumes "prime (p::nat)" and "p dvd prod_mset M" and "\<forall>q \<in># M. prime q"
  shows "p \<in># M"
  sorry

text \<open>Existence of a factorization: stated here (so the blueprint marks it
  \<open>named\<close>) but the proof is deferred.\<close>

theorem factorization_exists:
  assumes "1 < (n::nat)"
  shows "\<exists>M. prime_factorization_of n M"
  sorry

theorem factorization_unique:
  assumes "prime_factorization_of n M" and "prime_factorization_of n N"
  shows "M = N"
  sorry

theorem fundamental_theorem_arithmetic:
  assumes "1 < (n::nat)"
  shows "\<exists>!M. prime_factorization_of n M"
  sorry

end
