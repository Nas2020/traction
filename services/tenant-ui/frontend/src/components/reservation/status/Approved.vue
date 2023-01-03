<template>
  <!-- Approved and ready to get wallet details with PW -->
  <Card class="info-card mt-4 mb-6">
    <template #title>
      <i class="pi pi-thumbs-up info-card-icon"></i> <br />
      APPROVED!
    </template>
    <template #content>
      <p>
        We have sent a reservation password to your email address on
        {{ formatDateLong(reservation.updated_at) }}.
      </p>
      <p>
        Please enter the reservation password below to validate your account.
      </p>

      <form @submit.prevent="handleSubmit(!v$.$invalid)">
        <div class="field">
          <Password
            v-model="v$.password.$model"
            class="w-full"
            input-class="w-full"
            toggle-mask
            :feedback="false"
            placeholder="Password"
          />
          <small v-if="v$.password.$invalid && submitted" class="p-error">
            {{ v$.password.required.$message }}
          </small>
          <Button type="submit" label="Validate" class="w-full mt-3" />
        </div>
      </form>
      <p>
        The reservation password is only valid for 48 hours from the time it was
        sent to your email address.
      </p>
    </template>
    <template #footer>
      <hr />
      (Please check your junk/spam folder before contacting us, as it is very
      common to have the email delivery problems because of automated filters.)
    </template>
  </Card>
</template>

<script setup lang="ts">
// Vue
import { reactive, ref } from 'vue';
// PrimeVue/Validation/etc
import Button from 'primevue/button';
import Card from 'primevue/card';
import Password from 'primevue/password';
import { required } from '@vuelidate/validators';
import { useVuelidate } from '@vuelidate/core';
import { useToast } from 'vue-toastification';
// Other Components
import { formatDateLong } from '@/helpers';
// State
import { useReservationStore } from '@/store';
import { storeToRefs } from 'pinia';

const toast = useToast();

const reservationStore = useReservationStore();
const { reservation } = storeToRefs(useReservationStore());

// Validation
const formFields = reactive({
  password: '',
});
const rules = {
  password: { required },
};
const v$ = useVuelidate(rules, formFields, { $scope: false });

// Password form submission
const submitted = ref(false);
const handleSubmit = async (isFormValid: boolean) => {
  submitted.value = true;

  if (!isFormValid) {
    return;
  }

  try {
    await reservationStore.checkIn(
      reservation.value.reservation_id,
      formFields.password
    );
  } catch (error) {
    toast.error(`Failure: ${error}`);
  } finally {
    submitted.value = false;
  }
};
</script>