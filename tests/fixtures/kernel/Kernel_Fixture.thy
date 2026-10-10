theory Kernel_Fixture
  imports Main
begin

ML_file "fixture_aux.ML"

lemma clean: "(n :: nat) + 0 = n"
  by simp

lemma admitted: "False"
  sorry

end
