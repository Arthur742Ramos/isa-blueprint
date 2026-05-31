theory Arith_Demo
  imports Main
begin

text \<open>
  A tiny demo theory used by the IsabelleBlueprint example project.
  The fact names referenced from \texttt{blueprint.md} are deliberately
  conservative aliases of standard library lemmas so that the demo
  builds against any modern Isabelle/HOL.
\<close>

definition add_def :: "nat \<Rightarrow> nat \<Rightarrow> nat"
  where "add_def m n = m + n"

lemma add_zero_right: "n + 0 = (n :: nat)"
  by simp

lemma add_zero_left: "0 + n = (n :: nat)"
  by simp

theorem add_zero_both: "n + 0 = (n :: nat) \<and> 0 + n = (n :: nat)"
  by (simp add: add_zero_right add_zero_left)

end
