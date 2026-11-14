#!/usr/bin/env bash
set -Eeuo pipefail

output_dir="${1:?usage: linux_cli_lab.sh OUTPUT_DIR}"
mkdir -p "$output_dir"
input_file="$output_dir/events.csv"
delivered_file="$output_dir/delivered.csv"

cat > "$input_file" <<'CSV'
order_id,status,amount
O001,delivered,100.00
O002,pending,250.00
O003,delivered,35.50
O004,canceled,18.00
CSV

delivered_total="$(grep -E '^O[0-9]+,delivered,' "$input_file" \
  | awk -F, '{total += $3; count += 1} END {printf "%.2f", total}')"
sed -n '1p' "$input_file" > "$delivered_file"
grep -E '^O[0-9]+,delivered,' "$input_file" \
  | sed 's/,delivered,/,Delivered,/' >> "$delivered_file"
chmod 600 "$delivered_file"
permission_mode="$(stat -c '%a' "$delivered_file")"
delivered_line_count="$(wc -l < "$delivered_file" | tr -d ' ')"
delivered_rows="$((delivered_line_count - 1))"

printf 'delivered_total=%s\n' "$delivered_total"
printf 'delivered_rows=%s\n' "$delivered_rows"
printf 'permission_mode=%s\n' "$permission_mode"
