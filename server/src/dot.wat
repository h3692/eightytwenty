;; int8 dot products with WASM SIMD: out[i] = sum_d vecs[i*1024+d] * q[d] for i < n (1024-d rows).
(module
  (memory (export "mem") 1) ;; grown by the caller to fit the library
  (func (export "scan") (param $vecs i32) (param $q i32) (param $out i32) (param $n i32)
    (local $i i32) (local $d i32) (local $p i32) (local $acc v128) (local $a v128) (local $b v128)
    (block $done
      (loop $rows
        (br_if $done (i32.ge_u (local.get $i) (local.get $n)))
        (local.set $acc (v128.const i32x4 0 0 0 0))
        (local.set $d (i32.const 0))
        (local.set $p (i32.add (local.get $vecs) (i32.shl (local.get $i) (i32.const 10))))
        (loop $cols
          (local.set $a (v128.load (i32.add (local.get $p) (local.get $d))))
          (local.set $b (v128.load (i32.add (local.get $q) (local.get $d))))
          (local.set $acc (i32x4.add (local.get $acc)
            (i32x4.add
              (i32x4.dot_i16x8_s (i16x8.extend_low_i8x16_s (local.get $a)) (i16x8.extend_low_i8x16_s (local.get $b)))
              (i32x4.dot_i16x8_s (i16x8.extend_high_i8x16_s (local.get $a)) (i16x8.extend_high_i8x16_s (local.get $b))))))
          (local.set $d (i32.add (local.get $d) (i32.const 16)))
          (br_if $cols (i32.lt_u (local.get $d) (i32.const 1024))))
        (i32.store (i32.add (local.get $out) (i32.shl (local.get $i) (i32.const 2)))
          (i32.add (i32.add (i32x4.extract_lane 0 (local.get $acc)) (i32x4.extract_lane 1 (local.get $acc)))
                   (i32.add (i32x4.extract_lane 2 (local.get $acc)) (i32x4.extract_lane 3 (local.get $acc)))))
        (local.set $i (i32.add (local.get $i) (i32.const 1)))
        (br $rows))))
)
