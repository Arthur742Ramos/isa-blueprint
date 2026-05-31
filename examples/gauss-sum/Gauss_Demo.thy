theory Gauss_Demo
  imports Main
begin

text \<open>
  Skeleton theory backing the Gauss-summation blueprint. The fact names match the
  `isabelle:` references in `blueprint.md`, so `isabelle-blueprint check` can
  resolve them once this session is built. Every fact below is a genuine theorem
  (no `sorry`), matching the `formal: proved` status declared in the blueprint.
\<close>

fun triangular :: "nat \<Rightarrow> nat" where
  "triangular 0 = 0"
| "triangular (Suc n) = triangular n + Suc n"

lemmas triangular_def = triangular.simps

lemma triangular_step:
  "2 * triangular (Suc n) = 2 * triangular n + 2 * Suc n"
  by simp

theorem gauss_formula:
  "2 * triangular n = n * (n + 1)"
  by (induction n) (simp_all add: triangular_step)

end
